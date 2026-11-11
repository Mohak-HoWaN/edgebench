"""INT8 calibration: choosing the pictures from a dataset version, recording exactly which, and laying them out for the
converter.

The chosen file list is stored in the artifact store and the conversion remembers only its hash, so an INT8 variant
can say which pictures it was calibrated on even if the dataset's own calibration subset is picked again later, and
two variants calibrated on the same pictures share a cache key (ADR 0002).
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from sqlmodel import Session

from .artifacts import sha256_file
from .dataset_import import DEFAULT_CALIBRATION, MIN_CALIBRATION, ImportProblem, choose_calibration, read_manifest
from .dataset_versions import find_version
from .models import Artifact, Dataset, DatasetVersion
from .services import Services


class CalibrationProblem(ValueError):
    """The calibration subset cannot be made; the message says why and is shown to the person."""


def distinct_images(images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per different picture: copies of the same file (same content, any name) count once.

    One picture repeated gave a worse INT8 model than 128 different ones (docs/phase-0-verdict.md), so fifty copies
    of one picture must not pass for fifty pictures.
    """
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for im in images:
        key = im.get("original_sha256") or im["original"]
        if key not in seen:
            seen.add(key)
            out.append(im)
    return out


def plan(s: Services, dataset_id: int, ref: str, count: int | None = None, seed: int | None = None) -> dict[str, Any]:
    """The calibration for a conversion: which version, which pictures (their list is stored; its hash is returned).

    With neither ``count`` nor ``seed`` the subset the dataset page already picked is used; otherwise a new seeded
    one is chosen. Fewer than 50 pictures is refused: one picture repeated gave a worse model than 128 different ones.
    """
    with Session(s.engine) as session:
        dataset = session.get(Dataset, dataset_id)
        version = find_version(session, dataset_id, ref) if dataset and not dataset.archived else None
        if version is None or version.status != "ready" or not version.artifact_sha256:
            raise CalibrationProblem("That version of the dataset is not ready, so it cannot be used for calibration.")
        sha, number, version_id, stored = version.artifact_sha256, version.number, version.id, version.calibration
    manifest = read_manifest(s.store.path(sha))
    images = distinct_images(manifest["images"])
    if count is None and seed is None and stored and stored.get("files"):
        wanted = set(stored["files"])
        files = sorted(im["original"] for im in images if im["original"] in wanted)
        chosen = {"seed": stored.get("seed", 0), "count": len(files), "files": files}
    else:
        try:
            chosen = choose_calibration(images, DEFAULT_CALIBRATION if count is None else count, seed or 0)
        except ImportProblem as exc:
            copies = len(manifest["images"]) - len(images)
            more = f" ({copies} more are copies of those)" if copies else ""
            raise CalibrationProblem(
                f"Calibration needs at least {MIN_CALIBRATION} different pictures; "
                f"this dataset has {len(images)}{more}."
            ) from exc
    if len(chosen["files"]) < MIN_CALIBRATION:
        raise CalibrationProblem(
            f"Calibration needs at least {MIN_CALIBRATION} pictures; this subset has {len(chosen['files'])}."
        )
    tmp = s.store.tmp / f"calibration-{version_id}-{chosen['seed']}.json"
    tmp.write_text(json.dumps(chosen["files"]), encoding="utf-8")
    list_sha = sha256_file(tmp)
    s.store.put_file(tmp, list_sha)
    with Session(s.engine) as session:
        if session.get(Artifact, list_sha) is None:
            session.add(Artifact(sha256=list_sha, kind="calibration", size=s.store.path(list_sha).stat().st_size))
            session.commit()
    return {
        "dataset_id": dataset_id,
        "dataset_version_id": version_id,
        "version": number,
        "seed": chosen["seed"],
        "count": len(chosen["files"]),
        "list_sha": list_sha,
    }


def extract(s: Services, calibration: dict[str, Any], dest: Path) -> int:
    """Write the calibration pictures into ``dest`` for the converter. Returns how many were written."""
    with Session(s.engine) as session:
        version = session.get(DatasetVersion, calibration["dataset_version_id"])
        sha = version.artifact_sha256 if version else None
    if sha is None or not s.store.exists(sha) or not s.store.exists(calibration["list_sha"]):
        raise CalibrationProblem(
            "The dataset version or the calibration list this conversion needs is gone from the store."
        )
    wanted = set(json.loads(s.store.path(calibration["list_sha"]).read_text(encoding="utf-8")))
    written = 0
    with zipfile.ZipFile(s.store.path(sha)) as z:
        for entry in read_manifest(s.store.path(sha))["images"]:
            if entry["original"] in wanted:
                (dest / Path(entry["file"]).name).write_bytes(z.read(entry["file"]))
                written += 1
    if written < MIN_CALIBRATION:
        raise CalibrationProblem(
            f"Only {written} of the calibration pictures could be read; at least {MIN_CALIBRATION} are needed."
        )
    return written
