"""Dataset versions: a dataset is a history of snapshots, like a repository.

A version is a *manifest*: the list of files (path, SHA-256, size) it consists of. The files are stored once, by hash,
in the artifact store and shared between versions, so a version that adds ten pictures to a thousand costs ten
pictures. Building a version lays its files out in a folder (hard links), runs the importer over it and stores the
normalised zip the agents read.

``build_version`` is the job that does that for a commit, a restore or a folder import; ``import_bundle`` rebuilds a
whole shared dataset (all its versions) from a bundle file made by ``export_bundle``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from sqlmodel import Session, col, select
from starlette.background import BackgroundTask

from . import queue
from .artifacts import sha256_file
from .dataset_import import HEIC_EXTENSIONS, IMAGE_EXTENSIONS, ImportProblem, import_directory
from .model_jobs import register_artifact
from .models import Dataset, DatasetVersion, MlModel
from .ndjson_import import expand_ndjson, is_ndjson
from .services import Services
from .worker import Cancelled, Handler, JobContext, OwnershipLost, PermanentError, register

log = logging.getLogger(__name__)
SIDE_SUFFIXES = {".txt", ".json", ".yaml", ".yml", ".csv", ".names", ".xml"}
FILE_SUFFIXES = IMAGE_EXTENSIONS | SIDE_SUFFIXES  # what a version may contain
BLOB_SUFFIXES = FILE_SUFFIXES | {
    ".zip",
    ".ndjson",
    ".jsonl",
}  # what may be uploaded (a zip or an NDJSON file is expanded into files)
SHA = re.compile(r"^[0-9a-f]{64}$")
BUNDLE_JSON = "edgebench-dataset.json"
MAX_PATH = 300


def clean_path(raw: str, allowed: set[str] = BLOB_SUFFIXES) -> str:
    """A relative path with forward slashes and no way out of the folder, or ``ValueError`` saying what is wrong."""
    path = PurePosixPath(raw.replace("\\", "/").strip().lstrip("/"))
    if not path.parts or len(str(path)) > MAX_PATH:
        raise ValueError("The file has no usable name.")
    if ".." in path.parts or ":" in path.parts[0] or any(part in ("", ".") for part in path.parts):
        raise ValueError(f"{raw!r} is not a safe path.")
    suffix = path.suffix.lower()
    if suffix in HEIC_EXTENSIONS:
        raise ValueError(f"{path.name}: HEIC photos are not supported yet. Convert them to JPEG first.")
    if suffix not in allowed:
        raise ValueError(
            f"{path.name}: not a kind of file a dataset holds (pictures, YOLO .txt, COCO .json, VOC .xml, .yaml, .csv)."
        )
    return str(path)


def publish(s: Services, dataset_id: int, version_id: int | None = None) -> None:
    s.publish({"type": "dataset.updated", "id": dataset_id, "version_id": version_id})


def head_version(session: Session, dataset: Dataset) -> DatasetVersion | None:
    return session.get(DatasetVersion, dataset.head_version_id) if dataset.head_version_id else None


def find_version(session: Session, dataset_id: int, ref: str) -> DatasetVersion | None:
    """``ref`` is a version number, or ``head`` for the newest finished one."""
    if ref == "head":
        d = session.get(Dataset, dataset_id)
        return head_version(session, d) if d is not None else None
    if not ref.isdigit():
        return None
    return session.exec(
        select(DatasetVersion).where(DatasetVersion.dataset_id == dataset_id, DatasetVersion.number == int(ref))
    ).first()


def diff(old: list[dict[str, Any]] | None, new: list[dict[str, Any]]) -> dict[str, Any]:
    """What changed between two manifests, as counts plus the first few paths of each kind."""
    before = {e["path"]: e["sha256"] for e in old or []}
    after = {e["path"]: e["sha256"] for e in new}
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(p for p in set(before) & set(after) if before[p] != after[p])
    keep = 20
    return {
        "added": len(added),
        "removed": len(removed),
        "modified": len(changed),
        "added_paths": added[:keep],
        "removed_paths": removed[:keep],
        "modified_paths": changed[:keep],
    }


def start_version(
    s: Services,
    dataset_id: int,
    message: str,
    *,
    add: list[dict[str, str]] | None = None,
    remove: list[str] | None = None,
    folder: str | None = None,
    base_version_id: int | None = None,
    model_id: int | None = None,
) -> DatasetVersion:
    """Create the next version (building) and queue the job that fills it in.

    ``base_version_id`` is the version whose files the new one starts from: the head for a commit, an older one
    for a restore.
    """
    with Session(s.engine) as session:
        dataset = session.get(Dataset, dataset_id)
        assert dataset is not None
        latest = session.exec(
            select(DatasetVersion.number)
            .where(DatasetVersion.dataset_id == dataset_id)
            .order_by(col(DatasetVersion.number).desc())
        ).first()
        version = DatasetVersion(
            dataset_id=dataset_id,
            number=(latest or 0) + 1,
            message=message.strip()[:300],
            parent_id=dataset.head_version_id,
            source_path=folder,
        )
        session.add(version)
        session.commit()
        session.refresh(version)
        assert version.id is not None
        version_id = version.id
        params = {
            "version_id": version_id,
            "add": add or [],
            "remove": remove or [],
            "folder": folder,
            "base_version_id": base_version_id,
            "model_id": model_id,
        }
    queue.enqueue(s.engine, "build_version", params, max_attempts=1)
    publish(s, dataset_id, version_id)
    with Session(s.engine) as session:
        out = session.get(DatasetVersion, version_id)
        assert out is not None
        return out


# --- building ---------------------------------------------------------------------------------------------------------


def store_blob(s: Services, source: Path) -> tuple[str, int]:
    """Put a file into the store by its hash (copying, so the original is untouched). Returns (sha256, size)."""
    sha = sha256_file(source)
    target = s.store.path(sha)
    if not target.exists():
        tmp = s.store.tmp / f"blob-{os.getpid()}-{sha[:12]}"
        shutil.copyfile(source, tmp)
        s.store.put_file(tmp, sha)
    return sha, source.stat().st_size


def _ingest_folder(s: Services, folder: Path, ctx: JobContext) -> list[dict[str, Any]]:
    files = [p for p in sorted(folder.rglob("*")) if p.is_file() and p.suffix.lower() in FILE_SUFFIXES]
    files = [p for p in files if not any(part.startswith((".", "__MACOSX")) for part in p.relative_to(folder).parts)]
    entries: list[dict[str, Any]] = []
    with Session(s.engine) as session:
        for n, path in enumerate(files):
            ctx.progress(0.3 * n / max(len(files), 1), f"Reading file {n + 1} of {len(files)}")
            sha, size = store_blob(s, path)
            register_artifact(session, sha, "file", size)
            entries.append({"path": path.relative_to(folder).as_posix(), "sha256": sha, "size": size})
        session.commit()
    return entries


def _unpack_zip(s: Services, sha: str, ctx: JobContext) -> list[dict[str, Any]]:
    """Turn an uploaded zip into files in the store. Entries that would escape their folder are refused."""
    entries: list[dict[str, Any]] = []
    max_files, max_bytes = s.settings.max_dataset_files, s.settings.max_dataset_unpacked_bytes
    try:
        with zipfile.ZipFile(s.store.path(sha)) as z, Session(s.engine) as session:
            members = [m for m in z.infolist() if not m.is_dir()]
            if len(members) > max_files:
                raise ImportProblem(f"That zip holds {len(members)} files; the limit is {max_files}.")
            if sum(m.file_size for m in members) > max_bytes:
                raise ImportProblem(
                    f"That zip unpacks to more than {max_bytes // 1024**3} GB, which is over the limit."
                )
            for n, member in enumerate(members):
                try:
                    path = clean_path(member.filename, FILE_SUFFIXES)
                except ValueError as exc:
                    if (
                        PurePosixPath(member.filename.replace("\\", "/")).suffix.lower()
                        in BLOB_SUFFIXES | HEIC_EXTENSIONS
                    ):
                        raise ImportProblem(f"That zip holds {exc}") from None
                    continue  # some other kind of file (a readme, a thumbnail cache): not part of the dataset
                ctx.progress(0.3 * n / max(len(members), 1), f"Unpacking file {n + 1} of {len(members)}")
                tmp = s.store.tmp / f"unzip-{os.getpid()}-{n}"
                with z.open(member) as src, tmp.open("wb") as out:
                    shutil.copyfileobj(src, out)
                blob = sha256_file(tmp)
                size = tmp.stat().st_size
                s.store.put_file(tmp, blob)
                register_artifact(session, blob, "file", size)
                entries.append({"path": path, "sha256": blob, "size": size})
            session.commit()
    except zipfile.BadZipFile:
        raise ImportProblem("That file is not a readable zip.") from None
    return entries


def materialise(s: Services, manifest: list[dict[str, Any]], dest: Path) -> None:
    """Lay the files of a manifest out as a folder (hard links where possible; the store shares the disk)."""
    for entry in manifest:
        source = s.store.path(entry["sha256"])
        if not source.exists():
            raise ImportProblem(f"The stored copy of {entry['path']} is missing.")
        target = dest / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(source, target)
        except OSError:
            shutil.copyfile(source, target)


def finish_build(
    s: Services, ctx: JobContext, version_id: int, manifest: list[dict[str, Any]], model_id: int | None
) -> int:
    """Import the files of ``manifest`` and complete the version. Returns the number of pictures."""
    with Session(s.engine) as session:
        version = session.get(DatasetVersion, version_id)
        assert version is not None
        parent = session.get(DatasetVersion, version.parent_id) if version.parent_id else None
        hint: list[str] | None = None
        if model_id is not None:
            m = session.get(MlModel, model_id)
            hint = list(m.class_names) if m is not None and m.class_names else None
        parent_manifest, parent_hash, parent_number = (
            (parent.manifest, parent.dataset_hash, parent.number) if parent is not None else (None, None, None)
        )
    workdir = s.store.new_workdir()
    try:
        folder = workdir / "files"
        folder.mkdir()
        materialise(s, manifest, folder)
        out = workdir / "dataset.zip"
        result = import_directory(folder, out, names_hint=hint, progress=lambda f, m: ctx.progress(0.3 + 0.7 * f, m))
        if parent_hash is not None and result.dataset_hash == parent_hash:
            raise ImportProblem(f"Nothing changed compared with version {parent_number}.")
        sha = sha256_file(out)
        s.store.put_file(out, sha)
        with Session(s.engine) as session:
            register_artifact(session, sha, "dataset", result.size_bytes)
            version = session.get(DatasetVersion, version_id)
            dataset = session.get(Dataset, version.dataset_id) if version else None
            if version is None or dataset is None or dataset.archived:
                return 0
            version.manifest = manifest
            version.changes = diff(parent_manifest, manifest) if parent_manifest is not None or parent is None else None
            version.format, version.image_count = result.format, result.image_count
            version.labelled_count, version.instance_count = result.labelled_count, result.instance_count
            version.class_names, version.names_generic = result.names, result.names_generic
            version.dataset_hash, version.artifact_sha256, version.size_bytes = (
                result.dataset_hash,
                sha,
                result.size_bytes,
            )
            version.stats, version.status, version.error = result.stats, "ready", None
            dataset.head_version_id = version.id
            session.add(version)
            session.add(dataset)
            session.commit()
            dataset_id = dataset.id
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    if dataset_id is not None:
        publish(s, dataset_id, version_id)
    return result.image_count


def _fail(s: Services, version_id: int, message: str) -> None:
    with Session(s.engine) as session:
        v = session.get(DatasetVersion, version_id)
        if v is not None:
            v.status, v.error = "failed", message
            session.add(v)
            session.commit()
            publish(s, v.dataset_id, version_id)


def _manifest_of(session: Session, version_id: int | None) -> dict[str, dict[str, Any]]:
    if version_id is None:
        return {}
    base = session.get(DatasetVersion, version_id)
    if base is None or base.manifest is None:
        raise ImportProblem(
            "That version's files were not kept (it was imported before versions existed), so it cannot be built on."
        )
    return {e["path"]: e for e in base.manifest}


def _collect_files(s: Services, ctx: JobContext, base: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """The new version's manifest: the base's files, minus what was removed, plus what was added or read."""
    files = dict(base)
    for removed in ctx.params.get("remove", []):
        prefix = removed.rstrip("/") + "/"
        for path in [p for p in files if p == removed or p.startswith(prefix)]:
            del files[path]
    added: list[dict[str, Any]] = []
    if ctx.params.get("folder"):
        folder = Path(ctx.params["folder"])
        if not folder.is_dir():
            raise ImportProblem(f"The folder {folder} is not there any more.")
        added += _ingest_folder(s, folder, ctx)
    ndjson_files: list[str] = []
    for item in ctx.params.get("add", []):
        if not SHA.match(item["sha256"]) or not s.store.exists(item["sha256"]):
            raise ImportProblem(f"{item['path']} was not uploaded completely. Upload it again.")
        if item["path"].lower().endswith(".zip"):
            added += _unpack_zip(s, item["sha256"], ctx)
        elif is_ndjson(item["path"]):
            ndjson_files.append(item["sha256"])
        else:
            size = s.store.path(item["sha256"]).stat().st_size
            added.append({"path": item["path"], "sha256": item["sha256"], "size": size})
    for sha in ndjson_files:  # after the rest, so the pictures sent along (or inside a zip) can be matched by name
        expanded, used = expand_ndjson(s, sha, added, ctx)
        added = [e for e in added if e["path"] not in used] + expanded
    for entry in added:
        files[entry["path"]] = entry
    if not files:
        raise ImportProblem("There are no files to build a dataset from.")
    return sorted(files.values(), key=lambda e: e["path"])


def make_build_handler(s: Services) -> Handler:
    def handler(ctx: JobContext) -> dict[str, Any] | None:
        version_id = int(ctx.params["version_id"])
        try:
            with Session(s.engine) as session:
                version = session.get(DatasetVersion, version_id)
                dataset = session.get(Dataset, version.dataset_id) if version else None
                if version is None or dataset is None or dataset.archived:
                    return {"skipped": "the dataset was removed"}
                base = _manifest_of(session, ctx.params.get("base_version_id"))
            manifest = _collect_files(s, ctx, base)
            return {"images": finish_build(s, ctx, version_id, manifest, ctx.params.get("model_id"))}
        except ImportProblem as exc:
            _fail(s, version_id, str(exc))  # the answer the job was asked for: shown on the version, the job is done
            return {"failed": str(exc)}
        except (Cancelled, OwnershipLost):
            _fail(s, version_id, "The import was stopped.")
            raise
        except Exception as exc:
            log.exception("building a dataset version failed", extra={"version_id": version_id})
            _fail(s, version_id, f"Building this version failed unexpectedly ({type(exc).__name__}).")
            raise PermanentError(str(exc)) from None

    return handler


# --- sharing ----------------------------------------------------------------------------------------------------------


def export_bundle(s: Services, dataset_id: int) -> tuple[Path, str, BackgroundTask]:
    """Write every finished version of a dataset, with its files, to one zip that another EdgeBench can import."""
    with Session(s.engine) as session:
        dataset = session.get(Dataset, dataset_id)
        assert dataset is not None
        versions = session.exec(
            select(DatasetVersion)
            .where(
                DatasetVersion.dataset_id == dataset_id,
                DatasetVersion.status == "ready",
                col(DatasetVersion.manifest).is_not(None),
            )
            .order_by(col(DatasetVersion.number))
        ).all()
        description = {
            "format": "edgebench-dataset",
            "version": 1,
            "name": dataset.name,
            "description": dataset.description,
            "versions": [
                {
                    "number": v.number,
                    "message": v.message,
                    "created_at": v.created_at.isoformat(),
                    "manifest": v.manifest,
                }
                for v in versions
            ],
        }
        name = dataset.name
    shas = sorted({e["sha256"] for v in versions for e in (v.manifest or [])})
    tmp = s.store.tmp / f"bundle-{os.getpid()}-{dataset_id}.zip"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:
        z.writestr(BUNDLE_JSON, json.dumps(description))
        for sha in shas:
            if s.store.exists(sha):
                z.write(s.store.path(sha), f"blobs/{sha}")
    return tmp, name, BackgroundTask(tmp.unlink, missing_ok=True)


def _read_bundle(s: Services, ctx: JobContext, bundle_sha: str) -> dict[str, Any]:
    """Check a bundle and move its files into the store. Returns its description."""
    with zipfile.ZipFile(s.store.path(bundle_sha)) as z:
        if z.getinfo(BUNDLE_JSON).file_size > 64 * 1024**2:
            raise ImportProblem("The bundle's description is unreasonably large.")
        description: dict[str, Any] = json.loads(z.read(BUNDLE_JSON))
        if description.get("format") != "edgebench-dataset":
            raise ImportProblem("That zip is not an EdgeBench dataset bundle.")
        wanted = {e["sha256"] for v in description["versions"] for e in v["manifest"]}
        if not all(SHA.match(x) for x in wanted):
            raise ImportProblem("The bundle lists a file with an invalid checksum.")
        with Session(s.engine) as session:
            for n, sha in enumerate(sorted(wanted)):
                ctx.progress(0.2 * n / max(len(wanted), 1), f"Reading file {n + 1} of {len(wanted)}")
                if s.store.exists(sha):
                    continue
                tmp = s.store.tmp / f"bundle-blob-{os.getpid()}-{n}"
                with z.open(f"blobs/{sha}") as src, tmp.open("wb") as out:
                    shutil.copyfileobj(src, out)
                if sha256_file(tmp) != sha:
                    tmp.unlink(missing_ok=True)
                    raise ImportProblem("A file in the bundle does not match its checksum; the bundle is damaged.")
                size = tmp.stat().st_size
                s.store.put_file(tmp, sha)
                register_artifact(session, sha, "file", size)
            session.commit()
    return description


def _build_bundle_versions(s: Services, ctx: JobContext, dataset_id: int, description: dict[str, Any]) -> int:
    built = 0
    for position, v in enumerate(description["versions"]):
        manifest = [
            {"path": clean_path(e["path"], FILE_SUFFIXES), "sha256": e["sha256"], "size": int(e["size"])}
            for e in v["manifest"]
        ]
        with Session(s.engine) as session:
            dataset = session.get(Dataset, dataset_id)
            if dataset is None or dataset.archived:
                return built
            version = DatasetVersion(
                dataset_id=dataset_id,
                number=int(v["number"]),
                message=str(v.get("message", ""))[:300],
                parent_id=dataset.head_version_id,
            )
            session.add(version)
            session.commit()
            session.refresh(version)
            assert version.id is not None
            version_id = version.id
        try:
            finish_build(s, ctx, version_id, manifest, None)
            built += 1
        except ImportProblem as exc:
            _fail(s, version_id, str(exc))
        ctx.progress(0.2 + 0.8 * (position + 1) / len(description["versions"]), f"Built version {v['number']}")
    return built


def make_bundle_handler(s: Services) -> Handler:
    def handler(ctx: JobContext) -> dict[str, Any] | None:
        dataset_id, bundle_sha = int(ctx.params["dataset_id"]), str(ctx.params["bundle_sha"])
        try:
            built = _build_bundle_versions(s, ctx, dataset_id, _read_bundle(s, ctx, bundle_sha))
            if not built:
                raise ImportProblem("None of the versions in that bundle could be built.")
            return {"versions": built}
        except (ImportProblem, KeyError, ValueError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
            message = (
                str(exc) if isinstance(exc, ImportProblem) else "That file is not a readable EdgeBench dataset bundle."
            )
            with Session(s.engine) as session:
                has_versions = session.exec(
                    select(DatasetVersion.id).where(DatasetVersion.dataset_id == dataset_id)
                ).first()
                if has_versions is None:
                    # nothing was built: leave a failed version that says why, so the dataset page can show it
                    failed = DatasetVersion(
                        dataset_id=dataset_id, number=1, message="Shared dataset", status="failed", error=message
                    )
                    session.add(failed)
                    session.commit()
            publish(s, dataset_id)
            return {"failed": message}

    return handler


def register_dataset_handlers(s: Services) -> None:
    register("build_version")(make_build_handler(s))
    register("import_bundle")(make_bundle_handler(s))
