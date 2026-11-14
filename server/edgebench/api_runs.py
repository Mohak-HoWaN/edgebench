from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from . import compat, failures, latency, queue
from .api_models import services
from .dataset_import import read_manifest
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
    warmup: int = Field(default=20, ge=0, le=10_000)  # per repeat
    iterations: int = Field(default=200, ge=1, le=100_000)  # per repeat
    repeats: int = Field(default=3, ge=1, le=100)  # ADR 0004: three give a wide interval, five or more a useful one
    telemetry: bool = True  # sample CPU, memory, clock and temperature in a separate process while the run goes
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
    format: str  # ONNX, OpenVINO, ncnn, TorchScript, or PyTorch for the baseline
    precision: str
    size_bytes: int | None  # the converted file(s), or the .pt itself for the baseline
    imgsz: int | None
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
    latency: dict[str, Any] | None  # headline latency with its interval over the repeats (latency.summary)
    diagnosis: list[str]  # facts that point at the tool, not the model, when a result looks wrong (see diagnose)
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


def cell_label(variant: Variant, size_note: str = "") -> str:
    """E.g. "ONNX FP32", or "OpenVINO INT8, 200 calibration images", or "ONNX FP32, not simplified"."""
    label = f"{variant.format} {variant.precision}{size_note}"
    calibration = variant.settings.get("calibration")
    if calibration:
        label += f", {calibration['count']} calibration images"
    if variant.settings.get("simplify") is False:
        label += ", not simplified"
    return label


def variant_label(variant: Variant | None, model: MlModel | None) -> str:
    """``cell_label`` plus the input size if it is not the model's own."""
    if variant is None:
        return BASELINE_LABEL
    own = model is None or not model.imgsz or variant.imgsz == model.imgsz
    return cell_label(variant, "" if own else f" at {variant.imgsz} px")


def diagnose(run: Run, model: MlModel | None, variant: Variant | None, device: Device | None) -> list[str]:
    """Why a result may be the tool's fault. Only facts that were recorded; nothing is tuned and nothing is guessed."""
    found: list[str] = []
    trained = (model.card or {}).get("trained_with") if model else None
    if variant is not None:
        why = compat.older_than_model(
            (variant.toolchain or {}).get("ultralytics"), trained, "This conversion was built by"
        )
    else:
        packages = (device.fingerprint or {}).get("packages") if device else None
        library = packages.get("ultralytics") if isinstance(packages, dict) else None
        why = compat.older_than_model(library, trained, "The device's agent has")
    if why:
        found.append(why)
    accuracy = (run.result or {}).get("accuracy") or {}
    if accuracy.get("available") and accuracy.get("recall") == 0:
        found.append("It found none of the labelled objects. Check that the dataset's classes and pictures suit it.")
    return found


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
        format=variant.format if variant else "PyTorch",
        precision=variant.precision if variant else "FP32",
        size_bytes=variant.size_bytes if variant else (model.size_bytes if model else None),
        imgsz=variant.imgsz if variant else (model.imgsz if model else None),
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
        latency=latency.summary((run.result or {}).get("speed")),
        diagnosis=diagnose(run, model, variant, device),
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


def prepare_run(session: Session, body: NewRun, versions: dict[str, str]) -> Prepared:
    """Check that everything a run needs exists and is ready. Raises a 422 that says which part is not."""
    model = session.get(MlModel, body.model_id)
    if model is None or model.archived or model.status != "ready" or not model.artifact_sha256:
        if model is not None and model.status == "incompatible" and model.error:
            raise HTTPException(422, f"{model.name} cannot be run yet. {model.error}")
        raise HTTPException(422, "That model is not ready to run.")
    variant = None
    if body.variant_id is not None:
        variant = session.get(Variant, body.variant_id)
        if variant is None or variant.model_id != model.id:
            raise HTTPException(422, "That conversion does not belong to this model.")
        if variant.state != "ready" or not variant.artifact_sha256:
            raise HTTPException(422, "That conversion is not finished, so it cannot be run.")
        if stale := compat.stale_reason(variant.toolchain, versions):
            # Not "your model is bad": a result from a variant the current converter did not build proves little.
            raise HTTPException(422, f"{model.name}, {variant_label(variant, model)}: {stale}")
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
        p = prepare_run(session, body, s.converter.info().versions)
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


@lru_cache(maxsize=4)
def _manifest(path: str) -> dict[str, Any]:
    return read_manifest(Path(path))


def _failure_inputs(request: Request, run_id: int, limit: int) -> tuple[dict[str, Any], Path, list[str]]:
    """What a failure list needs: the analysis, the dataset version's zip, and the dataset's class names."""
    s = services(request)
    with Session(s.engine) as session:
        run = _run_or_404(session, run_id)
        model = session.get(MlModel, run.model_id) if run.model_id else None
        version = session.get(DatasetVersion, run.dataset_version_id) if run.dataset_version_id else None
        sha = (run.result or {}).get("predictions_sha")
        if run.outcome != "done" or not sha or not s.store.exists(sha):
            raise HTTPException(
                409, "This run kept no per-picture detections, so there is nothing to list. Run it again."
            )
        if (
            model is None
            or version is None
            or not version.artifact_sha256
            or not s.store.exists(version.artifact_sha256)
        ):
            raise HTTPException(409, "The model or the dataset version of this run is no longer available.")
        zip_path = s.store.path(version.artifact_sha256)
        model_names = list(model.class_names or [])
    manifest = _manifest(str(zip_path))
    names = list(manifest["names"])
    pictures = failures.predictions(str(s.store.path(sha))).get("pictures", {})
    return failures.analyse(manifest["images"], names, pictures, model_names, limit), zip_path, names


@router.get("/api/runs/{run_id}/failures")
def run_failures(run_id: int, request: Request, limit: int = Query(100, ge=1, le=1000)) -> dict[str, Any]:
    """The pictures this run got wrong (missed, wrongly named, made up), worst first, with the real and found boxes."""
    return _failure_inputs(request, run_id, limit)[0]


@router.get("/api/runs/{run_id}/failures.zip")
def run_failures_zip(run_id: int, request: Request, images: str = Query(min_length=1, max_length=8000)) -> Response:
    """The chosen pictures (by index, from the failure list) as a folder for the next annotation round."""
    try:
        wanted = {int(x) for x in images.split(",") if x}
    except ValueError:
        raise HTTPException(422, "The pictures must be numbers separated by commas.") from None
    result, zip_path, names = _failure_inputs(request, run_id, 1000)
    picked = [p for p in result["pictures"] if p["index"] in wanted]
    if not picked:
        raise HTTPException(404, "None of those pictures is in this run's list of mistakes.")
    return Response(
        failures.export(zip_path, picked, names),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="mistakes-run-{run_id}.zip"'},
    )


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
