from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from . import queue
from .api_models import services
from .dataset_versions import find_version
from .models import Dataset, DatasetVersion, Device, Job, MlModel, Run, Variant
from .security import same_origin
from .services import Services

router = APIRouter()
guarded = [Depends(same_origin)]
BASELINE_LABEL = "PyTorch (.pt) baseline"
RUNTIME_OF = {"ONNX": "onnx", "OpenVINO": "openvino", "ncnn": "ncnn", "TorchScript": "torchscript"}


class RunParams(BaseModel):
    threads: int = Field(default=4, ge=1, le=1024)
    warmup: int = Field(default=10, ge=0, le=10_000)
    iterations: int = Field(default=100, ge=1, le=100_000)
    accuracy: bool = True
    # Ultralytics' validator settings, so accuracy is comparable with model.val()
    conf: float = Field(default=0.001, gt=0, lt=1)
    iou: float = Field(default=0.7, gt=0, lt=1)
    max_det: int = Field(default=300, ge=1, le=10_000)
    max_images: int | None = Field(default=None, ge=1)
    # Logical CPU numbers the benchmark is pinned to (empty or missing: let the operating system decide)
    cpu_list: list[int] | None = Field(default=None, max_length=1024)


class NewRun(BaseModel):
    model_id: int
    variant_id: int | None = None  # None runs the .pt itself (the baseline)
    dataset_id: int
    dataset_version: int | None = None  # None: the newest finished version
    device_id: int
    params: RunParams = RunParams()


class RunOut(BaseModel):
    id: int
    experiment_id: int | None
    status: str
    model_id: int | None
    model_name: str | None
    variant_id: int | None
    variant_label: str
    runtime: str
    dataset_id: int | None
    dataset_name: str | None
    dataset_version: int | None
    device_id: int | None
    device_name: str | None
    device_kind: str | None
    params: dict[str, Any] | None
    progress: float | None
    message: str | None
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


def status_of(run: Run, job: Job | None) -> str:
    if run.outcome:
        return run.outcome
    if job is None:
        return "queued"
    return {"queued": "queued", "claimed": "running", "running": "running", "done": "failed"}.get(job.state, job.state)


def runtime_for(variant: Variant | None) -> str:
    return "pytorch" if variant is None else RUNTIME_OF[variant.format]


def variant_label(variant: Variant | None, model: MlModel | None) -> str:
    """E.g. "ONNX FP32", plus the input size if it is not the model's own, and a note if not simplified."""
    if variant is None:
        return BASELINE_LABEL
    label = f"{variant.format} {variant.precision}"
    if model is not None and model.imgsz and variant.imgsz != model.imgsz:
        label += f" at {variant.imgsz} px"
    if variant.settings.get("simplify") is False:
        label += ", not simplified"
    return label


def run_out(s: Services, session: Session, run: Run) -> RunOut:
    assert run.id is not None
    job = session.get(Job, run.job_id) if run.job_id else None
    model = session.get(MlModel, run.model_id) if run.model_id else None
    variant = session.get(Variant, run.variant_id) if run.variant_id else None
    dataset = session.get(Dataset, run.dataset_id) if run.dataset_id else None
    version = session.get(DatasetVersion, run.dataset_version_id) if run.dataset_version_id else None
    device = session.get(Device, run.device_id) if run.device_id else None
    status = status_of(run, job)
    live = s.progress.get(run.job_id or -1, {})
    return RunOut(
        id=run.id,
        experiment_id=run.experiment_id,
        status=status,
        model_id=run.model_id,
        model_name=model.name if model else None,
        variant_id=run.variant_id,
        variant_label=variant_label(variant, model),
        runtime=runtime_for(variant),
        dataset_id=run.dataset_id,
        dataset_name=dataset.name if dataset else None,
        dataset_version=version.number if version else None,
        device_id=run.device_id,
        device_name=device.name if device else None,
        device_kind=device.kind if device else None,
        params=run.params,
        progress=live.get("fraction") if status == "running" else None,
        message=live.get("message") if status == "running" else None,
        result=run.result,
        error=run.error or (job.error if job and status in ("failed", "lost") else None),
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


def _run_or_404(session: Session, run_id: int) -> Run:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "There is no such run.")
    return run


@dataclass
class Prepared:
    model: MlModel
    variant: Variant | None
    dataset: Dataset
    version: DatasetVersion
    device: Device


def check_cpu_settings(device: Device, params: RunParams) -> None:
    """The device reports how many logical CPUs it has; do not accept a thread count or CPU number beyond that."""
    logical = (device.fingerprint or {}).get("logical_cores")
    if not isinstance(logical, int) or logical < 1:
        return
    cpus = params.cpu_list or []
    if any(c < 0 or c >= logical for c in cpus):
        raise HTTPException(
            422, f"{device.name} has CPUs 0 to {logical - 1}; the list asks for one that does not exist."
        )
    if len(set(cpus)) != len(cpus):
        raise HTTPException(422, "The CPU list names the same CPU twice.")
    limit = len(cpus) or logical
    if params.threads > limit:
        plural = "s" if limit != 1 else ""
        raise HTTPException(
            422, f"{device.name} can run {limit} thread{plural} here; the run asks for {params.threads}."
        )


def prepare_run(session: Session, body: NewRun) -> Prepared:
    """Check that everything a run needs exists and is ready. Raises a 422 that says which part is not."""
    model = session.get(MlModel, body.model_id)
    if model is None or model.archived or model.status != "ready" or not model.artifact_sha256:
        raise HTTPException(422, "That model is not ready to run.")
    variant = None
    if body.variant_id is not None:
        variant = session.get(Variant, body.variant_id)
        if variant is None or variant.model_id != model.id:
            raise HTTPException(422, "That conversion does not belong to this model.")
        if variant.state != "ready" or not variant.artifact_sha256:
            raise HTTPException(422, "That conversion is not finished, so it cannot be run.")
    dataset = session.get(Dataset, body.dataset_id)
    if dataset is None or dataset.archived:
        raise HTTPException(422, "That dataset is not here.")
    ref = "head" if body.dataset_version is None else str(body.dataset_version)
    version = find_version(session, dataset.id or 0, ref)
    if version is None or version.status != "ready" or not version.artifact_sha256:
        raise HTTPException(422, "That version of the dataset is not ready.")
    device = session.get(Device, body.device_id)
    if device is None or device.revoked or device.token_hash is None:
        raise HTTPException(422, "That device has not connected an agent yet.")
    check_cpu_settings(device, body.params)
    return Prepared(model, variant, dataset, version, device)


def create_run(s: Services, body: NewRun, experiment_id: int | None = None) -> int:
    with Session(s.engine) as session:
        p = prepare_run(session, body)
        run = Run(
            experiment_id=experiment_id,
            model_id=p.model.id,
            variant_id=body.variant_id,
            dataset_id=p.dataset.id,
            dataset_version_id=p.version.id,
            device_id=p.device.id,
            params=body.params.model_dump(),
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        assert run.id is not None
        # One attempt: if the agent vanishes mid-run the run is marked lost, not silently repeated on a warmer machine.
        run.job_id = queue.enqueue(s.engine, "benchmark", {"run_id": run.id}, device_id=p.device.id, max_attempts=1)
        session.add(run)
        session.commit()
        run_id = run.id
    s.publish({"type": "run.updated", "id": run_id})
    return run_id


def run_spec(s: Services, run_id: int) -> dict[str, Any]:
    """What the agent needs to run: where to fetch each file, and every setting, so a run can be repeated exactly."""
    with Session(s.engine) as session:
        run = _run_or_404(session, run_id)
        model = session.get(MlModel, run.model_id) if run.model_id else None
        version = session.get(DatasetVersion, run.dataset_version_id) if run.dataset_version_id else None
        variant = session.get(Variant, run.variant_id) if run.variant_id else None
        if model is None or version is None or not model.artifact_sha256 or not version.artifact_sha256:
            raise HTTPException(409, "The model or the dataset of this run is gone.")
        if variant is None:
            artifact: dict[str, Any] = {"layout": "file", "sha256": model.artifact_sha256, "main": "model.pt"}
        else:
            assert variant.artifact_sha256 and variant.main_file
            folder = s.store.path(variant.artifact_sha256)
            files = sorted(p.name for p in folder.iterdir() if p.is_file()) if folder.is_dir() else []
            if variant.main_file not in files:
                raise HTTPException(409, "The converted files of this run are gone from the store.")
            artifact = {
                "layout": "bundle",
                "sha256": variant.artifact_sha256,
                "files": files,
                "main": variant.main_file,
            }
        return {
            "run_id": run_id,
            "kind": runtime_for(variant),
            "artifact": artifact,
            "dataset": {"sha256": version.artifact_sha256, "names_generic": version.names_generic},
            "model_names": model.class_names or [],
            "imgsz": variant.imgsz if variant else (model.imgsz or 640),
            "params": run.params or {},
        }


@router.get("/api/runs")
def list_runs(
    request: Request, limit: int = Query(100, ge=1, le=500), experiment_id: int | None = None
) -> list[RunOut]:
    s = services(request)
    with Session(s.engine) as session:
        query = select(Run).order_by(col(Run.id).desc()).limit(limit)
        if experiment_id is not None:
            query = query.where(Run.experiment_id == experiment_id)
        return [run_out(s, session, r) for r in session.exec(query)]


@router.get("/api/runs/{run_id}")
def get_run(run_id: int, request: Request) -> RunOut:
    s = services(request)
    with Session(s.engine) as session:
        return run_out(s, session, _run_or_404(session, run_id))


@router.post("/api/runs", status_code=201, dependencies=guarded)
def start_run(body: NewRun, request: Request) -> RunOut:
    """One run on its own. The experiment form makes several at once; this is for scripts and the run-again button."""
    s = services(request)
    run_id = create_run(s, body)
    with Session(s.engine) as session:
        return run_out(s, session, _run_or_404(session, run_id))


@router.post("/api/runs/{run_id}/again", status_code=201, dependencies=guarded)
def run_again(run_id: int, request: Request) -> RunOut:
    """The same measurement once more: same model, conversion, dataset version, device and settings."""
    s = services(request)
    with Session(s.engine) as session:
        old = _run_or_404(session, run_id)
        version = session.get(DatasetVersion, old.dataset_version_id) if old.dataset_version_id else None
        if old.model_id is None or old.dataset_id is None or old.device_id is None or version is None:
            raise HTTPException(409, "That run cannot be repeated.")
        body = NewRun(
            model_id=old.model_id,
            variant_id=old.variant_id,
            dataset_id=old.dataset_id,
            dataset_version=version.number,
            device_id=old.device_id,
            params=RunParams(**(old.params or {})),
        )
        experiment_id = old.experiment_id
    new_id = create_run(s, body, experiment_id)
    with Session(s.engine) as session:
        return run_out(s, session, _run_or_404(session, new_id))


def cancel_one(s: Services, run: Run) -> bool:
    """Ask for a waiting or running run to stop. False if it had already finished."""
    job = queue.get(s.engine, run.job_id) if run.job_id is not None else None
    if run.outcome is not None or job is None or job.state not in ("queued", "claimed", "running"):
        return False
    assert job.id is not None
    queue.request_cancel(s.engine, job.id)
    return True


@router.post("/api/runs/{run_id}/cancel", dependencies=guarded)
def cancel_run(run_id: int, request: Request) -> RunOut:
    s = services(request)
    with Session(s.engine) as session:
        run = _run_or_404(session, run_id)
        if not cancel_one(s, run):
            raise HTTPException(409, "This run has already finished.")
    s.publish({"type": "run.updated", "id": run_id})
    with Session(s.engine) as session:
        return run_out(s, session, _run_or_404(session, run_id))


@router.delete("/api/runs/{run_id}", status_code=204, dependencies=guarded)
def remove_run(run_id: int, request: Request) -> Response:
    """Take a finished, failed, lost or cancelled run off the results; a waiting or running one is cancelled first."""
    s = services(request)
    with Session(s.engine) as session:
        run = _run_or_404(session, run_id)
        job = session.get(Job, run.job_id) if run.job_id else None
        if status_of(run, job) in ("queued", "running"):
            raise HTTPException(409, "Cancel this run before removing it.")
        session.delete(run)
        session.commit()
    s.publish({"type": "run.updated", "id": run_id})
    return Response(status_code=204)
