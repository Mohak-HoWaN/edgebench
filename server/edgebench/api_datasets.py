"""Datasets as repositories: a name, a history of versions, and files uploaded once and shared between versions."""

from __future__ import annotations

import asyncio
import zipfile
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.responses import Response as RawResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from . import queue
from .api_models import _safe, _zip_response, services
from .artifacts import TooLarge
from .dataset_import import DEFAULT_CALIBRATION, ImportProblem, choose_calibration, read_manifest
from .dataset_versions import clean_path, export_bundle, find_version, start_version
from .model_jobs import register_artifact
from .models import Dataset, DatasetVersion, MlModel
from .security import same_origin
from .services import Services

router = APIRouter()
guarded = [Depends(same_origin)]


class VersionOut(BaseModel):
    id: int
    number: int
    message: str
    created_at: datetime
    status: str
    error: str | None
    is_head: bool
    has_files: bool  # False for a version imported before versions existed: its files were not kept
    format: str | None
    image_count: int
    labelled_count: int
    instance_count: int
    class_names: list[str] | None
    names_generic: bool
    dataset_hash: str | None
    size_bytes: int
    stats: dict[str, Any] | None
    calibration: dict[str, Any] | None
    changes: dict[str, Any] | None
    source_path: str | None


class DatasetOut(BaseModel):
    id: int
    name: str
    description: str
    created_at: datetime
    version_count: int
    building: bool
    head: VersionOut | None
    versions: list[VersionOut] | None = None


class NewDataset(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)


class EditDataset(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class FileRef(BaseModel):
    path: str
    sha256: str = Field(pattern="^[0-9a-f]{64}$")


class Commit(BaseModel):
    message: str = Field(default="", max_length=300)
    add: list[FileRef] = []
    remove: list[str] = []
    model_id: int | None = None  # take class names from this model when the files have none


class FolderImport(BaseModel):
    path: str
    dataset_id: int | None = None  # add to this dataset; a new one is made when omitted
    name: str | None = Field(default=None, max_length=120)
    message: str = Field(default="", max_length=300)
    model_id: int | None = None


class CalibrationRequest(BaseModel):
    count: int = DEFAULT_CALIBRATION
    seed: int = 0


def _version_out(v: DatasetVersion, head_id: int | None, with_files: bool = False) -> VersionOut:
    assert v.id is not None
    calibration = v.calibration
    if calibration is not None and not with_files:
        calibration = {k: x for k, x in calibration.items() if k != "files"}
    return VersionOut(
        id=v.id,
        number=v.number,
        message=v.message,
        created_at=v.created_at,
        status=v.status,
        error=v.error,
        is_head=v.id == head_id,
        has_files=v.manifest is not None,
        format=v.format,
        image_count=v.image_count,
        labelled_count=v.labelled_count,
        instance_count=v.instance_count,
        class_names=v.class_names,
        names_generic=v.names_generic,
        dataset_hash=v.dataset_hash,
        size_bytes=v.size_bytes,
        stats=v.stats,
        calibration=calibration,
        changes=v.changes,
        source_path=v.source_path,
    )


def _out(session: Session, d: Dataset, with_versions: bool = False) -> DatasetOut:
    assert d.id is not None
    versions = list(
        session.exec(
            select(DatasetVersion).where(DatasetVersion.dataset_id == d.id).order_by(col(DatasetVersion.number).desc())
        ).all()
    )
    head = next((v for v in versions if v.id == d.head_version_id), None)
    return DatasetOut(
        id=d.id,
        name=d.name,
        description=d.description,
        created_at=d.created_at,
        version_count=sum(1 for v in versions if v.status == "ready"),
        building=any(v.status == "building" for v in versions),
        head=_version_out(head, d.head_version_id) if head else None,
        versions=[_version_out(v, d.head_version_id) for v in versions] if with_versions else None,
    )


def _dataset_or_404(session: Session, dataset_id: int) -> Dataset:
    d = session.get(Dataset, dataset_id)
    if d is None or d.archived:
        raise HTTPException(404, "There is no such dataset.")
    return d


def _version_or_404(session: Session, dataset_id: int, ref: str) -> DatasetVersion:
    _dataset_or_404(session, dataset_id)
    v = find_version(session, dataset_id, ref)
    if v is None:
        raise HTTPException(
            404, "There is no such version." if ref != "head" else "This dataset has no finished version yet."
        )
    return v


def _check_model(session: Session, model_id: int | None) -> None:
    if model_id is not None and session.get(MlModel, model_id) is None:
        raise HTTPException(422, "There is no such model to take the class names from.")


@lru_cache(maxsize=4)
def _manifest(path: str) -> dict[str, Any]:
    return read_manifest(Path(path))


# --- datasets ---------------------------------------------------------------------------------------------------------


@router.get("/api/datasets")
def list_datasets(request: Request) -> list[DatasetOut]:
    with Session(services(request).engine) as session:
        rows = session.exec(select(Dataset).where(col(Dataset.archived).is_(False)).order_by(col(Dataset.id).desc()))
        return [_out(session, d) for d in rows]


@router.post("/api/datasets", status_code=201, dependencies=guarded)
def create_dataset(body: NewDataset, request: Request) -> DatasetOut:
    """Make an empty dataset. Pictures are added with uploads and a commit."""
    s = services(request)
    with Session(s.engine) as session:
        d = Dataset(name=body.name.strip(), description=body.description.strip())
        session.add(d)
        session.commit()
        session.refresh(d)
        out = _out(session, d)
    s.publish({"type": "dataset.updated", "id": out.id})
    return out


@router.get("/api/datasets/{dataset_id}")
def get_dataset(dataset_id: int, request: Request) -> DatasetOut:
    with Session(services(request).engine) as session:
        return _out(session, _dataset_or_404(session, dataset_id), with_versions=True)


@router.patch("/api/datasets/{dataset_id}", dependencies=guarded)
def edit_dataset(dataset_id: int, body: EditDataset, request: Request) -> DatasetOut:
    s = services(request)
    with Session(s.engine) as session:
        d = _dataset_or_404(session, dataset_id)
        if body.name is not None:
            d.name = body.name.strip()
        if body.description is not None:
            d.description = body.description.strip()
        session.add(d)
        session.commit()
        out = _out(session, d, with_versions=True)
    s.publish({"type": "dataset.updated", "id": dataset_id})
    return out


@router.delete("/api/datasets/{dataset_id}", status_code=204, dependencies=guarded)
def archive_dataset(dataset_id: int, request: Request) -> Response:
    """Hide a dataset. Its files stay in the store, and runs that used it keep their results."""
    s = services(request)
    with Session(s.engine) as session:
        d = _dataset_or_404(session, dataset_id)
        d.archived = True
        session.add(d)
        session.commit()
    s.publish({"type": "dataset.updated", "id": dataset_id})
    return Response(status_code=204)


# --- adding files: upload each, then commit them as a version ----------------------------------------


@router.post("/api/datasets/{dataset_id}/blobs", dependencies=guarded)
async def upload_file(dataset_id: int, request: Request, x_path: str = Header()) -> dict[str, Any]:
    """Upload one file (a picture, a label file, a zip) as the raw request body.

    ``X-Path`` is its path inside the dataset, URL-encoded. The dataset does not change until the files are committed.
    """
    s = services(request)
    with Session(s.engine) as session:
        _dataset_or_404(session, dataset_id)
    try:
        path = clean_path(unquote(x_path))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    limit = s.settings.max_dataset_upload_bytes if path.lower().endswith(".zip") else s.settings.max_upload_bytes
    try:
        tmp, sha, size = await s.store.save_stream(request.stream(), limit)
    except TooLarge:
        raise HTTPException(413, f"{path} is larger than the {limit // 1024**2} MB limit.") from None
    if size == 0 and not path.lower().endswith(".txt"):  # an empty label file is real: a picture with nothing in it
        tmp.unlink(missing_ok=True)
        raise HTTPException(422, f"{path} is empty.")
    s.store.put_file(tmp, sha)
    with Session(s.engine) as session:
        register_artifact(session, sha, "file", size)
        session.commit()
    return {"path": path, "sha256": sha, "size": size}


def _check_commit(s: Services, session: Session, dataset_id: int, body: Commit) -> list[dict[str, str]]:
    _check_model(session, body.model_id)
    add: list[dict[str, str]] = []
    for ref in body.add:
        try:
            path = clean_path(ref.path)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        if not s.store.exists(ref.sha256):
            raise HTTPException(422, f"{path} was not uploaded. Upload it before committing.")
        add.append({"path": path, "sha256": ref.sha256})
    return add


@router.post("/api/datasets/{dataset_id}/commit", status_code=202, dependencies=guarded)
def commit(dataset_id: int, body: Commit, request: Request) -> VersionOut:
    """Make a new version: the current files, minus ``remove``, plus ``add`` (a zip is unpacked into its files)."""
    s = services(request)
    with Session(s.engine) as session:
        dataset = _dataset_or_404(session, dataset_id)
        add = _check_commit(s, session, dataset_id, body)
        if not add and not body.remove:
            raise HTTPException(422, "Add some files or remove some before committing.")
        if dataset.head_version_id is None and not add:
            raise HTTPException(422, "A new dataset needs pictures first.")
        base = dataset.head_version_id
        building = session.exec(
            select(DatasetVersion.id).where(
                DatasetVersion.dataset_id == dataset_id, DatasetVersion.status == "building"
            )
        ).first()
        if building is not None:
            raise HTTPException(409, "A version is still being built. Wait for it to finish, then commit again.")
    version = start_version(
        s,
        dataset_id,
        body.message or ("Add files" if add else "Remove files"),
        add=add,
        remove=body.remove,
        base_version_id=base,
        model_id=body.model_id,
    )
    with Session(s.engine) as session:
        return _version_out(version, None)


@router.post("/api/datasets/from-folder", status_code=202, dependencies=guarded)
def import_folder(body: FolderImport, request: Request) -> DatasetOut:
    """Read a folder on the machine the server runs on as a new version (of a new dataset unless one is given)."""
    s = services(request)
    folder = Path(body.path.strip().strip('"'))
    if not folder.is_absolute() or not folder.is_dir():
        raise HTTPException(422, "Give the full path of a folder that exists on the machine running the server.")
    with Session(s.engine) as session:
        _check_model(session, body.model_id)
        if body.dataset_id is not None:
            dataset = _dataset_or_404(session, body.dataset_id)
        else:
            dataset = Dataset(name=(body.name or folder.name).strip())
            session.add(dataset)
            session.commit()
            session.refresh(dataset)
        assert dataset.id is not None
        dataset_id, base = dataset.id, dataset.head_version_id
    start_version(
        s,
        dataset_id,
        body.message or f"Import {folder.name}",
        folder=str(folder),
        base_version_id=base,
        model_id=body.model_id,
    )
    with Session(s.engine) as session:
        return _out(session, _dataset_or_404(session, dataset_id), with_versions=True)


# --- one version ------------------------------------------------------------------------------------------


@router.get("/api/datasets/{dataset_id}/versions/{ref}")
def get_version(dataset_id: int, ref: str, request: Request) -> VersionOut:
    with Session(services(request).engine) as session:
        d = _dataset_or_404(session, dataset_id)
        return _version_out(_version_or_404(session, dataset_id, ref), d.head_version_id)


def _ready_zip(request: Request, dataset_id: int, ref: str) -> tuple[Path, DatasetVersion]:
    s = services(request)
    with Session(s.engine) as session:
        v = _version_or_404(session, dataset_id, ref)
        if v.status != "ready" or not v.artifact_sha256 or not s.store.exists(v.artifact_sha256):
            raise HTTPException(409, "This version has not been built (yet).")
        return s.store.path(v.artifact_sha256), v


@router.get("/api/datasets/{dataset_id}/versions/{ref}/images")
async def list_images(
    dataset_id: int, ref: str, request: Request, offset: int = Query(0, ge=0), limit: int = Query(24, ge=1, le=200)
) -> dict[str, Any]:
    """Pictures with their boxes (relative) for the previews, one page at a time."""
    path, _ = _ready_zip(request, dataset_id, ref)
    manifest = await asyncio.to_thread(_manifest, str(path))
    page = manifest["images"][offset : offset + limit]
    return {
        "total": len(manifest["images"]),
        "images": [
            {
                "index": offset + i,
                "original": im["original"],
                "width": im["width"],
                "height": im["height"],
                "source": im["source"],
                "labels": im["labels"],
            }
            for i, im in enumerate(page)
        ],
    }


@router.get("/api/datasets/{dataset_id}/versions/{ref}/images/{index}/file")
async def image_file(dataset_id: int, ref: str, index: int, request: Request) -> RawResponse:
    path, _ = _ready_zip(request, dataset_id, ref)
    manifest = await asyncio.to_thread(_manifest, str(path))
    if not 0 <= index < len(manifest["images"]):
        raise HTTPException(404, "There is no such picture.")

    def read() -> bytes:
        with zipfile.ZipFile(path) as z:
            return z.read(manifest["images"][index]["file"])

    return RawResponse(
        await asyncio.to_thread(read), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"}
    )


@router.post("/api/datasets/{dataset_id}/versions/{ref}/calibration", dependencies=guarded)
async def make_calibration(dataset_id: int, ref: str, body: CalibrationRequest, request: Request) -> VersionOut:
    """Pick (again) the calibration subset: seeded, mixing capture sources, at least 50 pictures."""
    s = services(request)
    path, version = _ready_zip(request, dataset_id, ref)
    manifest = await asyncio.to_thread(_manifest, str(path))
    try:
        chosen = choose_calibration(manifest["images"], body.count, body.seed)
    except ImportProblem as exc:
        raise HTTPException(422, str(exc)) from None
    with Session(s.engine) as session:
        v = session.get(DatasetVersion, version.id)
        d = _dataset_or_404(session, dataset_id)
        assert v is not None
        v.calibration = chosen
        session.add(v)
        session.commit()
        session.refresh(v)
        return _version_out(v, d.head_version_id, with_files=True)


@router.get("/api/datasets/{dataset_id}/versions/{ref}/download")
def download_version(
    dataset_id: int, ref: str, request: Request, kind: str = Query("files", pattern="^(files|normalised)$")
) -> FileResponse:
    """A version as a zip: ``files`` as uploaded (to restore or share), ``normalised`` as the agents read it."""
    s = services(request)
    with Session(s.engine) as session:
        d = _dataset_or_404(session, dataset_id)
        v = _version_or_404(session, dataset_id, ref)
        if v.status != "ready":
            raise HTTPException(409, "This version has not been built (yet).")
        base = f"{_safe(d.name)}-v{v.number}"
        manifest, artifact = v.manifest, v.artifact_sha256
    if kind == "normalised":
        if not artifact or not s.store.exists(artifact):
            raise HTTPException(404, "The normalised copy is gone from the store.")
        return FileResponse(s.store.path(artifact), filename=f"{base}-normalised.zip", media_type="application/zip")
    if manifest is None:
        raise HTTPException(
            409,
            "The original files of this version were not kept (it predates versions). Download the normalised one.",
        )
    entries = [(e["path"], s.store.path(e["sha256"])) for e in manifest if s.store.exists(e["sha256"])]
    return _zip_response(entries, s.store.tmp, f"{base}.zip")


@router.post("/api/datasets/{dataset_id}/versions/{ref}/restore", status_code=202, dependencies=guarded)
def restore_version(dataset_id: int, ref: str, request: Request) -> VersionOut:
    """Make the files of an older version the newest version. History is kept: nothing is deleted."""
    s = services(request)
    with Session(s.engine) as session:
        old = _version_or_404(session, dataset_id, ref)
        if old.status != "ready" or old.manifest is None:
            raise HTTPException(409, "That version's files were not kept, so it cannot be restored.")
        if session.exec(
            select(DatasetVersion.id).where(
                DatasetVersion.dataset_id == dataset_id, DatasetVersion.status == "building"
            )
        ).first():
            raise HTTPException(409, "A version is still being built. Wait for it to finish first.")
        old_id, number = old.id, old.number
    version = start_version(s, dataset_id, f"Restore version {number}", base_version_id=old_id)
    return _version_out(version, None)


@router.delete("/api/datasets/{dataset_id}/versions/{ref}", status_code=204, dependencies=guarded)
def discard_version(dataset_id: int, ref: str, request: Request) -> Response:
    """Throw away a version that failed to build. A finished version is part of the history and stays."""
    s = services(request)
    with Session(s.engine) as session:
        v = _version_or_404(session, dataset_id, ref)
        if v.status != "failed":
            raise HTTPException(409, "Only a version that failed can be discarded.")
        session.delete(v)
        session.commit()
    s.publish({"type": "dataset.updated", "id": dataset_id})
    return Response(status_code=204)


# --- sharing ------------------------------------------------------------------------------------------


@router.get("/api/datasets/{dataset_id}/export")
def export_dataset(dataset_id: int, request: Request) -> FileResponse:
    """The whole dataset, every version with its files, as one bundle that another EdgeBench can import."""
    s = services(request)
    with Session(s.engine) as session:
        d = _dataset_or_404(session, dataset_id)
        if d.head_version_id is None:
            raise HTTPException(409, "There is nothing to share yet.")
        name = _safe(d.name)
    path, _, cleanup = export_bundle(s, dataset_id)
    return FileResponse(path, filename=f"{name}.ebdataset.zip", media_type="application/zip", background=cleanup)


@router.post("/api/datasets/import-bundle", status_code=202, dependencies=guarded)
async def import_bundle(
    request: Request, x_filename: str = Header(), name: str | None = Query(default=None, max_length=120)
) -> DatasetOut:
    """Import a dataset someone shared (a bundle from ``export``), with all its versions."""
    s = services(request)
    filename = Path(unquote(x_filename)).name
    limit = s.settings.max_dataset_upload_bytes
    try:
        tmp, sha, size = await s.store.save_stream(request.stream(), limit)
    except TooLarge:
        raise HTTPException(413, f"That file is larger than the {limit // 1024**3} GB limit.") from None
    try:
        if size == 0 or not zipfile.is_zipfile(tmp):
            raise HTTPException(422, "That file is not a readable zip.")
        s.store.put_file(tmp, sha)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    default_name = filename.removesuffix(".zip").removesuffix(".ebdataset") or "Shared dataset"
    with Session(s.engine) as session:
        register_artifact(session, sha, "dataset-bundle", size)
        d = Dataset(name=(name or default_name).strip())
        session.add(d)
        session.commit()
        session.refresh(d)
        assert d.id is not None
        dataset_id = d.id
        out = _out(session, d, with_versions=True)
    queue.enqueue(s.engine, "import_bundle", {"dataset_id": dataset_id, "bundle_sha": sha}, max_attempts=1)
    s.publish({"type": "dataset.updated", "id": dataset_id})
    return out
