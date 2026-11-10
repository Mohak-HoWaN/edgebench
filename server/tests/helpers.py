from __future__ import annotations

import time
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlmodel import Session

from edgebench.models import Job, utcnow


def make_stale(engine: Engine, job_id: int) -> None:
    """Pretend the job's worker stopped sending heartbeats an hour ago.

    Back-dating the row is exact; sleeping and hoping the clock ticked is not (Windows timers are about 15 ms coarse).
    """
    with Session(engine) as session:
        job = session.get(Job, job_id)
        assert job is not None
        job.heartbeat_at = utcnow() - timedelta(hours=1)
        session.add(job)
        session.commit()


# --- datasets: create, upload files, commit, wait ---------------------------------------------


def upload_file(c: TestClient, dataset_id: int, path: str, data: bytes) -> dict[str, Any]:
    r = c.post(f"/api/datasets/{dataset_id}/blobs", content=data, headers={"x-path": quote(path)})
    assert r.status_code == 200, r.text
    return dict(r.json())


def wait_version(
    c: TestClient, dataset_id: int, ref: str = "head", status: str = "ready", timeout: float = 30
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        r = c.get(f"/api/datasets/{dataset_id}/versions/{ref}")
        if r.status_code == 200:
            last = r.json()
            if last["status"] == status:
                return last
            if last["status"] == "failed" and status != "failed":
                raise AssertionError(last["error"])
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {status}; last: {last}")


def commit_files(
    c: TestClient,
    dataset_id: int,
    files: dict[str, bytes],
    message: str = "",
    *,
    remove: list[str] | None = None,
    model_id: int | None = None,
) -> dict[str, Any]:
    """Upload ``files`` and commit them. Returns the new version (building)."""
    add = [upload_file(c, dataset_id, path, data) for path, data in files.items()]
    body: dict[str, Any] = {"message": message, "add": [{"path": a["path"], "sha256": a["sha256"]} for a in add]}
    if remove:
        body["remove"] = remove
    if model_id is not None:
        body["model_id"] = model_id
    r = c.post(f"/api/datasets/{dataset_id}/commit", json=body)
    assert r.status_code == 202, r.text
    return dict(r.json())


def folder_files(folder: Path) -> dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def make_dataset(c: TestClient, folder: Path, name: str = "shelf", message: str = "First pictures") -> dict[str, Any]:
    """Create a dataset from a folder of files and wait for version 1. Returns the dataset (with its head)."""
    created = c.post("/api/datasets", json={"name": name}).json()
    commit_files(c, created["id"], folder_files(folder), message)
    wait_version(c, created["id"], "1")
    return dict(c.get(f"/api/datasets/{created['id']}").json())
