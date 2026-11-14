from __future__ import annotations

import asyncio
import os
import re
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select
from starlette.background import BackgroundTask

from . import calibration, compat, queue
from .artifacts import TooLarge
from .matrix import BY_NAME
from .model_jobs import add_variant, cancel_variant, ensure_matrix, register_artifact, retry_variant
from .models import MlModel, Variant
from .ptscan import scan_checkpoint
from .security import same_origin
from .services import Services

router = APIRouter()
guarded = [Depends(same_origin)]


class VariantOut(BaseModel):
    id: int
    op: str
    format: str
    precision: str
    imgsz: int
    settings: dict[str, Any]
    state: str
    mismatch: bool
    cached: bool
    size_bytes: int | None
    seconds: float | None
    verify: dict[str, Any] | None
    error: str | None
    has_log: bool
    built_with: dict[str, str] | None  # converter library versions that made it; None: before they were recorded
    stale: str | None  # why it no longer matches the converter (rebuild it), when it does not
    updated_at: datetime


class ModelOut(BaseModel):
    id: int
    name: str
    filename: str
    size_bytes: int
    status: str
    error: str | None
    task: str | None
    imgsz: int | None
    parameters: int | None
    gflops: float | None
    class_names: list[str] | None
    card: dict[str, Any] | None  # where the file came from and whether this converter can read it (compat.check)
    sha256: str | None
    created_at: datetime
    variant_counts: dict[str, int]
    variants: list[VariantOut] | None = None


class NewVariant(BaseModel):
    op: str
    imgsz: int = Field(ge=32, le=2048)
    simplify: bool = True  # only the ONNX FP32 export has this choice


class NewInt8(BaseModel):
    op: str  # openvino_int8 or onnx_int8
    imgsz: int | None = Field(default=None, ge=32, le=2048)  # None: the model's own size
    dataset_id: int  # the pictures the quantizer learns the value ranges from
    dataset_version: int | None = None  # None: the newest finished version
    count: int | None = Field(default=None, ge=1, le=5000)  # None (with no seed): the subset the dataset already picked
    seed: int | None = None


class ConverterOut(BaseModel):
    available: bool
    message: str | None
    python: str | None
    versions: dict[str, str]
    missing: list[str]


def services(request: Request) -> Services:
    s: Services = request.app.state.services
    return s


def _variant_out(v: Variant, versions: dict[str, str]) -> VariantOut:
    assert v.id is not None
    return VariantOut(
        id=v.id,
        op=v.op,
        format=v.format,
        precision=v.precision,
        imgsz=v.imgsz,
        settings=v.settings,
        state=v.state,
        mismatch=v.mismatch,
        cached=v.cached,
        size_bytes=v.size_bytes,
        seconds=v.seconds,
        verify=v.verify,
        error=v.error,
        has_log=bool(v.log),
        built_with=v.toolchain,
        stale=compat.stale_reason(v.toolchain, versions) if v.state == "ready" else None,
        updated_at=v.updated_at,
    )


def _model_out(s: Services, session: Session, m: MlModel, with_variants: bool) -> ModelOut:
    assert m.id is not None
    versions = s.converter.info().versions
    variants = list(session.exec(select(Variant).where(Variant.model_id == m.id).order_by(col(Variant.id))).all())
    counts: dict[str, int] = {}
    for v in variants:
        counts[v.state] = counts.get(v.state, 0) + 1
    return ModelOut(
        id=m.id,
        name=m.name,
        filename=m.filename,
        size_bytes=m.size_bytes,
        status=m.status,
        error=m.error,
        task=m.task,
        imgsz=m.imgsz,
        parameters=m.parameters,
        gflops=m.gflops,
        class_names=m.class_names,
        card=m.card,
        sha256=m.artifact_sha256,
        created_at=m.created_at,
        variant_counts=counts,
        variants=[_variant_out(v, versions) for v in variants] if with_variants else None,
    )


def _model_or_404(session: Session, model_id: int) -> MlModel:
    m = session.get(MlModel, model_id)
    if m is None or m.archived:
        raise HTTPException(404, "There is no such model.")
    return m


@router.get("/api/converter")
async def converter_status(request: Request) -> ConverterOut:
    info = await asyncio.to_thread(services(request).converter.info)
    return ConverterOut(
        available=info.available, message=info.message, python=info.python, versions=info.versions, missing=info.missing
    )


@router.post("/api/converter/refresh", dependencies=guarded)
async def converter_refresh(request: Request) -> ConverterOut:
    """Look at the converter environment again, for example after upgrading a library in it."""
    info = await asyncio.to_thread(services(request).converter.info, True)
    return ConverterOut(
        available=info.available, message=info.message, python=info.python, versions=info.versions, missing=info.missing
    )


@router.get("/api/models")
def list_models(request: Request) -> list[ModelOut]:
    with Session(services(request).engine) as session:
        rows = session.exec(
            select(MlModel).where(col(MlModel.archived).is_(False)).order_by(col(MlModel.id).desc())
        ).all()
        return [_model_out(services(request), session, m, False) for m in rows]


@router.get("/api/models/{model_id}")
def get_model(model_id: int, request: Request) -> ModelOut:
    with Session(services(request).engine) as session:
        return _model_out(services(request), session, _model_or_404(session, model_id), True)


@router.post("/api/models", status_code=201, dependencies=guarded)
async def upload_model(request: Request, response: Response, x_filename: str = Header()) -> ModelOut:
    """Upload a ``.pt`` checkpoint as the raw request body (the filename travels in ``X-Filename``, URL-encoded).

    The file is streamed to disk and hashed, then scanned for pickle imports a model never needs, before it is stored.
    """
    s = services(request)
    name = Path(unquote(x_filename)).name
    if not name.lower().endswith(".pt"):
        raise HTTPException(422, "Only PyTorch checkpoints (.pt files) can be uploaded.")
    declared = request.headers.get("content-length")
    limit_mb = s.settings.max_upload_bytes // 1024**2
    if declared is not None and declared.isdigit() and int(declared) > s.settings.max_upload_bytes:
        raise HTTPException(413, f"That file is larger than the {limit_mb} MB limit.")
    try:
        tmp, sha, size = await s.store.save_stream(request.stream(), s.settings.max_upload_bytes)
    except TooLarge:
        raise HTTPException(413, f"That file is larger than the {limit_mb} MB limit.") from None
    try:
        if size == 0:
            raise HTTPException(422, "That file is empty.")
        scan = await asyncio.to_thread(scan_checkpoint, tmp)
        if not scan.ok:
            raise HTTPException(422, scan.problem)
        s.store.put_file(tmp, sha)
    except BaseException:
        tmp.unlink(missing_ok=True)  # refused, or something broke: never leave the upload behind (a no-op once stored)
        raise
    with Session(s.engine) as session:
        register_artifact(session, sha, "model", size)
        existing = session.exec(
            select(MlModel).where(MlModel.artifact_sha256 == sha, col(MlModel.archived).is_(False))
        ).first()
        if existing is not None:
            response.status_code = 200  # the same file again: show the model that is already here
            return _model_out(services(request), session, existing, False)
        model = MlModel(name=Path(name).stem, filename=name, size_bytes=size, artifact_sha256=sha, status="inspecting")
        session.add(model)
        session.commit()
        session.refresh(model)
        assert model.id is not None
        model_id = model.id
        out = _model_out(services(request), session, model, False)
    queue.enqueue(s.engine, "inspect", {"model_id": model_id})
    s.publish({"type": "model.updated", "id": model_id})
    return out


@router.post("/api/models/{model_id}/inspect", dependencies=guarded)
def reread_model(model_id: int, request: Request) -> ModelOut:
    """Read the model card again, for example after the converter environment was set up."""
    s = services(request)
    with Session(s.engine) as session:
        m = _model_or_404(session, model_id)
        if m.status == "ready":
            raise HTTPException(409, "This model has already been read.")
        m.status, m.error = "inspecting", None
        session.add(m)
        session.commit()
    s.converter.info(refresh=True)
    queue.enqueue(s.engine, "inspect", {"model_id": model_id})
    s.publish({"type": "model.updated", "id": model_id})
    with Session(s.engine) as session:
        return _model_out(services(request), session, _model_or_404(session, model_id), True)


@router.post("/api/models/{model_id}/convert", dependencies=guarded)
async def convert_model(model_id: int, request: Request) -> ModelOut:
    """Queue every cell of the matrix that is not already converted or in progress."""
    s = services(request)
    with Session(s.engine) as session:
        if _model_or_404(session, model_id).status != "ready":
            raise HTTPException(409, "This model has not been read yet, so it cannot be converted.")
    await asyncio.to_thread(ensure_matrix, s, model_id)
    with Session(s.engine) as session:
        return _model_out(services(request), session, _model_or_404(session, model_id), True)


@router.post("/api/models/{model_id}/variants", status_code=201, dependencies=guarded)
async def add_custom_variant(model_id: int, body: NewVariant, request: Request) -> ModelOut:
    """Add a conversion of your own: a format and precision at another input size, or an unsimplified ONNX export."""
    s = services(request)
    if body.op not in BY_NAME:
        raise HTTPException(422, f"Unknown conversion {body.op!r}. Choose one of: {', '.join(BY_NAME)}.")
    if body.imgsz % 32:
        raise HTTPException(422, "The input size must be a multiple of 32 (the detector works on a 32-pixel grid).")
    if body.op != "onnx_fp32" and not body.simplify:
        raise HTTPException(422, "Only the ONNX FP32 export can be left unsimplified.")
    with Session(s.engine) as session:
        if _model_or_404(session, model_id).status != "ready":
            raise HTTPException(409, "This model has not been read yet, so it cannot be converted.")
    await asyncio.to_thread(add_variant, s, model_id, body.op, body.imgsz, simplify=body.simplify)
    with Session(s.engine) as session:
        return _model_out(services(request), session, _model_or_404(session, model_id), True)


@router.post("/api/models/{model_id}/int8", status_code=201, dependencies=guarded)
async def add_int8_variant(model_id: int, body: NewInt8, request: Request) -> ModelOut:
    """Add an INT8 conversion, calibrated on pictures of a dataset version (at least 50, mixing capture sources).

    The accuracy check is a run: put the INT8 variant and the .pt baseline in one experiment and read the drift.
    """
    s = services(request)
    op = BY_NAME.get(body.op)
    if op is None or not op.calibrated:
        raise HTTPException(422, f"{body.op!r} is not an INT8 conversion. Choose openvino_int8 or onnx_int8.")
    with Session(s.engine) as session:
        model = _model_or_404(session, model_id)
        if model.status != "ready":
            raise HTTPException(409, "This model has not been read yet, so it cannot be converted.")
        imgsz = body.imgsz or model.imgsz
    if not imgsz or imgsz % 32:
        raise HTTPException(422, "The input size must be a multiple of 32 (the detector works on a 32-pixel grid).")
    ref = "head" if body.dataset_version is None else str(body.dataset_version)
    try:
        plan = await asyncio.to_thread(calibration.plan, s, body.dataset_id, ref, body.count, body.seed)
    except calibration.CalibrationProblem as exc:
        raise HTTPException(422, str(exc)) from None
    await asyncio.to_thread(add_variant, s, model_id, body.op, imgsz, calibration_plan=plan)
    with Session(s.engine) as session:
        return _model_out(services(request), session, _model_or_404(session, model_id), True)


@router.delete("/api/models/{model_id}", status_code=204, dependencies=guarded)
def archive_model(model_id: int, request: Request) -> Response:
    """Hide a model and stop its queued conversions. Its files stay in the store."""
    s = services(request)
    with Session(s.engine) as session:
        m = _model_or_404(session, model_id)
        m.archived = True
        session.add(m)
        waiting = [
            v.id for v in session.exec(select(Variant).where(Variant.model_id == model_id)).all() if v.id is not None
        ]
        session.commit()
    for variant_id in waiting:
        cancel_variant(s, variant_id)  # a cell that is not waiting or running is left as it is
    s.publish({"type": "model.updated", "id": model_id})
    return Response(status_code=204)


def _variant_or_404(session: Session, variant_id: int) -> Variant:
    v = session.get(Variant, variant_id)
    if v is None:
        raise HTTPException(404, "There is no such conversion.")
    return v


@router.post("/api/variants/{variant_id}/retry", dependencies=guarded)
def retry(variant_id: int, request: Request) -> VariantOut:
    s = services(request)
    with Session(s.engine) as session:
        _variant_or_404(session, variant_id)
    if not retry_variant(s, variant_id):
        raise HTTPException(
            409,
            "Only a failed, unavailable or cancelled conversion, or one built by an older converter, can be retried.",
        )
    with Session(s.engine) as session:
        return _variant_out(_variant_or_404(session, variant_id), services(request).converter.info().versions)


@router.post("/api/variants/{variant_id}/cancel", dependencies=guarded)
def cancel(variant_id: int, request: Request) -> VariantOut:
    s = services(request)
    with Session(s.engine) as session:
        _variant_or_404(session, variant_id)
    if not cancel_variant(s, variant_id):
        raise HTTPException(409, "Only a conversion that is waiting or running can be cancelled.")
    with Session(s.engine) as session:
        return _variant_out(_variant_or_404(session, variant_id), services(request).converter.info().versions)


def _bundle_files(s: Services, v: Variant) -> list[Path]:
    """The files of a finished conversion, read from the store's folder (not from names the converter reported)."""
    if v.state != "ready" or not v.artifact_sha256:
        raise HTTPException(409, "This conversion is not finished, so there is nothing to download.")
    folder = s.store.path(v.artifact_sha256)
    if not folder.is_dir():
        raise HTTPException(404, "The converted file is gone from the store. Retry the conversion to make it again.")
    return sorted(p for p in folder.iterdir() if p.is_file())


def _zip_response(entries: list[tuple[str, Path]], store_tmp: Path, filename: str) -> FileResponse:
    fd, name = tempfile.mkstemp(dir=store_tmp, prefix="download-", suffix=".zip")
    os.close(fd)
    tmp = Path(name)
    # Weights barely compress, so storing them is much faster than deflating them.
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:
        for arcname, path in entries:
            z.write(path, arcname)
    return FileResponse(
        tmp, filename=filename, media_type="application/zip", background=BackgroundTask(tmp.unlink, missing_ok=True)
    )


def variant_slug(model: MlModel, v: Variant) -> str:
    """The op name, plus the input size or a note when the cell is not the model's default build."""
    slug = v.op
    if model.imgsz and v.imgsz != model.imgsz:
        slug += f"-{v.imgsz}px"
    if v.settings.get("simplify") is False:
        slug += "-unsimplified"
    return slug


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "model"


@router.get("/api/variants/{variant_id}/download")
def download_variant(variant_id: int, request: Request) -> FileResponse:
    """A converted model: the file itself when the format is one file (ONNX, TorchScript), a zip when it is several."""
    s = services(request)
    with Session(s.engine) as session:
        v = _variant_or_404(session, variant_id)
        model = _model_or_404(session, v.model_id)  # a removed model's files are not offered
        files = _bundle_files(s, v)
        base = f"{_safe(model.name)}-{variant_slug(model, v)}"
    if len(files) == 1:
        return FileResponse(files[0], filename=base + files[0].suffix, media_type="application/octet-stream")
    return _zip_response([(p.name, p) for p in files], s.store.tmp, base + ".zip")


@router.get("/api/models/{model_id}/download")
def download_all(model_id: int, request: Request) -> FileResponse:
    """Every finished conversion of a model in one zip, one folder per variant."""
    s = services(request)
    with Session(s.engine) as session:
        m = _model_or_404(session, model_id)
        rows = session.exec(
            select(Variant).where(Variant.model_id == model_id, Variant.state == "ready").order_by(col(Variant.id))
        ).all()
        entries = [
            (f"{variant_slug(m, v)}/{p.name}", p)
            for v in rows
            if s.store.exists(v.artifact_sha256)
            for p in _bundle_files(s, v)
        ]
        name = _safe(m.name)
    if not entries:
        raise HTTPException(409, "Nothing has been converted yet, so there is nothing to download.")
    return _zip_response(entries, s.store.tmp, f"{name}-variants.zip")


@router.get("/api/variants/{variant_id}/log")
def variant_log(variant_id: int, request: Request) -> PlainTextResponse:
    with Session(services(request).engine) as session:
        return PlainTextResponse(_variant_or_404(session, variant_id).log or "")
