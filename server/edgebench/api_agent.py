"""What agents call (ADR 0003): outbound HTTP only. Enrol with a one-time token, then long-poll for jobs.

Every route except ``/agent/enroll`` needs the device token. Agents send no ``Origin`` header, so they pass the
same-origin check; a hostile web page would still need a valid token to do anything here.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from . import package, queue
from .api_models import services
from .api_runs import run_spec
from .artifacts import sha256_file
from .devices import authenticate, hash_token, kind_from_fingerprint, new_token
from .model_jobs import register_artifact
from .models import Device, Job, Run, utcnow
from .queue import Claimed
from .security import same_origin
from .services import Services

router = APIRouter(prefix="/agent")
SHA = re.compile(r"^[0-9a-f]{64}$")
LONG_POLL_SECONDS = 25.0
POLL_EVERY = 1.0


class EnrollRequest(BaseModel):
    token: str
    fingerprint: dict[str, Any]
    agent_version: str = ""
    name: str | None = Field(default=None, max_length=60)


class EnrollResponse(BaseModel):
    device_id: int
    device_token: str
    name: str
    kind: str


class Beat(BaseModel):
    job_id: int | None = None
    fraction: float | None = None
    message: str | None = None
    agent_version: str | None = None


class Result(BaseModel):
    job_id: int
    ok: bool
    kind: str = "failed"  # failed, unavailable or cancelled when not ok
    error: str | None = None
    result: dict[str, Any] | None = None
    log: str | None = None


def _touch(session: Session, device: Device, agent_version: str | None = None) -> None:
    device.last_seen_at = utcnow()
    if agent_version:
        device.agent_version = agent_version
    session.add(device)
    session.commit()


def _claimed(job: Job) -> Claimed:
    assert job.id is not None
    return Claimed(job.id, job.type, job.params, job.attempts, job.max_attempts)


def _own_job(session: Session, device: Device, job_id: int) -> Job:
    job = session.get(Job, job_id)
    if job is None or job.device_id != device.id:
        raise HTTPException(404, "That job is not yours.")
    return job


@router.post("/enroll", dependencies=[Depends(same_origin)])
def enroll(body: EnrollRequest, request: Request) -> EnrollResponse:
    s = services(request)
    throttle, ip = request.app.state.auth.enroll_throttle, request.client.host if request.client else "-"
    if wait := throttle.retry_after(ip):
        raise HTTPException(429, f"Too many wrong tokens. Try again in {wait} s.", headers={"Retry-After": str(wait)})
    with Session(s.engine) as session:
        device = session.exec(select(Device).where(Device.enroll_hash == hash_token(body.token.strip()))).first()
        expires = device.enroll_expires_at if device else None
        if device is None or device.revoked or expires is None or expires < utcnow():
            throttle.fail(ip)
            raise HTTPException(401, "That enrolment token is not valid or has expired. Create a new one in the app.")
        token = new_token("eb-device")
        device.token_hash, device.enroll_hash, device.enroll_expires_at = hash_token(token), None, None
        device.fingerprint, device.kind = body.fingerprint, kind_from_fingerprint(body.fingerprint)
        device.agent_version = body.agent_version or None
        if body.name:
            device.name = body.name
        _touch(session, device)
        assert device.id is not None
        out = EnrollResponse(device_id=device.id, device_token=token, name=device.name, kind=device.kind or "pc")
    s.publish({"type": "device.updated", "id": out.device_id})
    return out


@router.get("/package/{name}")
def agent_package(name: str, request: Request) -> Response:
    """The agent's source package for ``pip install``. Public on purpose: it holds no secret (see package.py)."""
    built = package.build(services(request).settings.agent_dir)
    if built is None or built[0] != name:
        raise HTTPException(404, "This server has no such agent package.")
    return Response(content=built[1], media_type="application/gzip")


@router.post("/claim")
async def claim(request: Request) -> Response:
    """Long poll: wait up to 25 s for a job for this device. 204 when there is none."""
    s = services(request)
    with Session(s.engine) as session:
        device = authenticate(session, request)
        assert device.id is not None
        device_id = device.id
        _touch(session, device)
    deadline = time.monotonic() + LONG_POLL_SECONDS
    while True:
        job = await asyncio.to_thread(queue.claim, s.engine, f"device-{device_id}", device_id=device_id)
        if job is not None:
            break
        if time.monotonic() >= deadline or await request.is_disconnected():
            return Response(status_code=204)
        await asyncio.sleep(POLL_EVERY)
    await asyncio.to_thread(queue.mark_running, s.engine, job)
    run_id = int(job.params["run_id"])
    try:
        spec = await asyncio.to_thread(run_spec, s, run_id)
    except HTTPException as exc:
        queue.fail(s.engine, job, str(exc.detail), retry=False)
        s.publish({"type": "run.updated", "id": run_id})
        return Response(status_code=204)
    with Session(s.engine) as session:
        run = session.get(Run, run_id)
        if run is not None and run.started_at is None:
            run.started_at = utcnow()
            session.add(run)
            session.commit()
    s.publish({"type": "run.updated", "id": run_id})
    return Response(content=json.dumps({"job_id": job.id, **spec}).encode(), media_type="application/json")


@router.post("/heartbeat", dependencies=[Depends(same_origin)])
def heartbeat(body: Beat, request: Request) -> dict[str, Any]:
    """Every 5 s. Keeps the device online and the job alive; the answer says whether to stop (cancelled or lost)."""
    s = services(request)
    with Session(s.engine) as session:
        device = authenticate(session, request)
        _touch(session, device, body.agent_version)
        if body.job_id is None:
            return {"ok": True, "cancel": False}
        job = _own_job(session, device, body.job_id)
        claimed = _claimed(job)
        cancel = bool(job.cancel_requested)
    if not queue.heartbeat(s.engine, claimed):
        return {"ok": False, "cancel": True, "lost": True}  # it was recovered as stale or finished: stop working on it
    if body.fraction is not None:
        s.progress[body.job_id] = {"fraction": body.fraction, "message": body.message or ""}
        s.publish({"type": "job.progress", "id": body.job_id, "fraction": body.fraction, "message": body.message or ""})
    return {"ok": True, "cancel": cancel}


@router.post("/result", dependencies=[Depends(same_origin)])
def result(body: Result, request: Request) -> dict[str, Any]:
    s = services(request)
    with Session(s.engine) as session:
        device = authenticate(session, request)
        _touch(session, device)
        job = _own_job(session, device, body.job_id)
        claimed = _claimed(job)
        run_id = int(job.params["run_id"])
    s.progress.pop(body.job_id, None)
    result_data = dict(body.result or {})
    predictions = result_data.pop("predictions", None)  # every picture's detections: kept as a file, not in the run row
    if predictions is not None and body.ok:
        result_data["predictions_sha"] = _keep_predictions(s, predictions)
    if body.ok:
        accepted = queue.complete(s.engine, claimed, {"run_id": run_id})
        outcome, error = "done", None
    elif body.kind == "cancelled":
        accepted = queue.mark_cancelled(s.engine, claimed)
        outcome, error = None, None
    else:
        # A run that could not be done (a runtime is missing, the model would not load) is an outcome of the run, not a
        # fault of the job: the job finished its work, which was to find that out. Like a conversion cell.
        outcome, error = ("unavailable" if body.kind == "unavailable" else "failed"), body.error or "The run failed."
        accepted = queue.complete(s.engine, claimed, {"run_id": run_id, "outcome": outcome})
    if not accepted:
        return {"accepted": False}  # the job was recovered as stale in the meantime; a late result is discarded
    with Session(s.engine) as session:
        run = session.get(Run, run_id)
        if run is not None:
            run.outcome, run.error, run.finished_at = outcome, error, utcnow()
            run.result = {**result_data, **({"log": body.log} if body.log else {})} or None
            session.add(run)
            session.commit()
    s.publish({"type": "run.updated", "id": run_id})
    return {"accepted": True}


def _keep_predictions(s: Services, predictions: dict[str, Any]) -> str:
    """Store a run's per-picture detections in the artifact store (one JSON file) and return its hash."""
    tmp = s.store.tmp / f"predictions-{os.getpid()}-{time.monotonic_ns()}"
    tmp.write_text(json.dumps(predictions, separators=(",", ":")), encoding="utf-8")
    sha = sha256_file(tmp)
    s.store.put_file(tmp, sha)
    with Session(s.engine) as session:
        register_artifact(session, sha, "predictions", s.store.path(sha).stat().st_size)
        session.commit()
    return sha


def _artifact_dir(request: Request, sha: str) -> Path:
    if not SHA.match(sha):
        raise HTTPException(404, "There is no such file.")
    path = services(request).store.path(sha)
    if not path.exists():
        raise HTTPException(404, "There is no such file.")
    return path


@router.get("/artifacts/{sha}")
def artifact_file(sha: str, request: Request) -> FileResponse:
    """A stored file (a model, a dataset zip). Supports ``Range`` so an interrupted download can resume."""
    with Session(services(request).engine) as session:
        authenticate(session, request)
    path = _artifact_dir(request, sha)
    if not path.is_file():
        raise HTTPException(404, "That artifact is a bundle: ask for one of its files by name.")
    return FileResponse(path, media_type="application/octet-stream")


@router.get("/artifacts/{sha}/{name}")
def artifact_bundle_file(sha: str, name: str, request: Request) -> FileResponse:
    with Session(services(request).engine) as session:
        authenticate(session, request)
    folder = _artifact_dir(request, sha)
    target = folder / name
    if not folder.is_dir() or Path(name).name != name or not target.is_file():
        raise HTTPException(404, "There is no such file.")
    return FileResponse(target, media_type="application/octet-stream")
