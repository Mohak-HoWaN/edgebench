"""Experiments: a named group of runs that share a dataset version, a device and settings, one model variant per run."""

from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from .api_models import services
from .api_runs import (
    NewRun,
    RunOut,
    RunParams,
    cancel_one,
    create_run,
    prepare_run,
    run_out,
    status_of,
)
from .models import Dataset, DatasetVersion, Device, Experiment, Job, MlModel, Run
from .security import same_origin
from .services import Services

router = APIRouter()
guarded = [Depends(same_origin)]
ACTIVE = ("queued", "running")


class Item(BaseModel):
    model_id: int
    variant_id: int | None = None  # None: the .pt baseline


class NewExperiment(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    notes: str = Field(default="", max_length=4000)
    dataset_id: int
    dataset_version: int | None = None
    device_id: int
    params: RunParams = RunParams()
    items: list[Item] = Field(min_length=1, max_length=200)


class ExperimentOut(BaseModel):
    id: int
    name: str
    notes: str
    created_at: datetime
    dataset_id: int | None
    dataset_name: str | None
    dataset_version: int | None
    device_id: int | None
    device_name: str | None
    params: dict[str, Any] | None
    status: str  # running, done, or partly (some runs failed, were lost or cancelled)
    counts: dict[str, int]
    models: list[str]
    runs: list[RunOut] | None = None


def _out(s: Services, session: Session, e: Experiment, with_runs: bool) -> ExperimentOut:
    assert e.id is not None
    runs = list(session.exec(select(Run).where(Run.experiment_id == e.id).order_by(col(Run.id))).all())
    outs = [run_out(s, session, r) for r in runs]
    counts: dict[str, int] = {}
    for o in outs:
        counts[o.status] = counts.get(o.status, 0) + 1
    if any(o.status in ACTIVE for o in outs):
        status = "running"
    elif outs and all(o.status == "done" for o in outs):
        status = "done"
    else:
        status = "partly"
    dataset = session.get(Dataset, e.dataset_id) if e.dataset_id else None
    version = session.get(DatasetVersion, e.dataset_version_id) if e.dataset_version_id else None
    device = session.get(Device, e.device_id) if e.device_id else None
    return ExperimentOut(
        id=e.id,
        name=e.name,
        notes=e.notes,
        created_at=e.created_at,
        dataset_id=e.dataset_id,
        dataset_name=dataset.name if dataset else None,
        dataset_version=version.number if version else None,
        device_id=e.device_id,
        device_name=device.name if device else None,
        params=e.params,
        status=status,
        counts=counts,
        models=sorted({o.model_name for o in outs if o.model_name}),
        runs=outs if with_runs else None,
    )


def _experiment_or_404(session: Session, experiment_id: int) -> Experiment:
    e = session.get(Experiment, experiment_id)
    if e is None:
        raise HTTPException(404, "There is no such experiment.")
    return e


@router.get("/api/experiments")
def list_experiments(request: Request) -> list[ExperimentOut]:
    """Every experiment, each with its runs (the Results page shows the best of them in one row)."""
    s = services(request)
    with Session(s.engine) as session:
        rows = session.exec(select(Experiment).order_by(col(Experiment.id).desc()))
        return [_out(s, session, e, with_runs=True) for e in rows]


@lru_cache(maxsize=8)
def _predictions(path: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    return data


@router.get("/api/experiments/{experiment_id}/inspect")
def inspect_picture(experiment_id: int, image: int, request: Request) -> dict[str, Any]:
    """What every run of the experiment found in one picture of its dataset version (relative boxes, for drawing)."""
    s = services(request)
    with Session(s.engine) as session:
        _experiment_or_404(session, experiment_id)
        runs = session.exec(select(Run).where(Run.experiment_id == experiment_id).order_by(col(Run.id))).all()
        out: list[dict[str, Any]] = []
        for r in runs:
            ro = run_out(s, session, r)
            model = session.get(MlModel, r.model_id) if r.model_id else None
            sha = (r.result or {}).get("predictions_sha")
            pictures = _predictions(str(s.store.path(sha)))["pictures"] if sha and s.store.exists(sha) else None
            out.append(
                {
                    "run_id": r.id,
                    "model_name": ro.model_name,
                    "variant_label": ro.variant_label,
                    "status": ro.status,
                    "class_names": model.class_names if model else [],
                    "detections": pictures.get(str(image)) if pictures is not None else None,
                }
            )
    return {"image": image, "runs": out}


@router.get("/api/experiments/{experiment_id}")
def get_experiment(experiment_id: int, request: Request) -> ExperimentOut:
    s = services(request)
    with Session(s.engine) as session:
        return _out(s, session, _experiment_or_404(session, experiment_id), with_runs=True)


@router.post("/api/experiments", status_code=201, dependencies=guarded)
def start_experiment(body: NewExperiment, request: Request) -> ExperimentOut:
    """Create the experiment and queue one run per item. Everything is checked first: all runs start or none do."""
    s = services(request)
    seen: set[tuple[int, int | None]] = set()
    runs: list[NewRun] = []
    for item in body.items:
        if (item.model_id, item.variant_id) in seen:
            continue
        seen.add((item.model_id, item.variant_id))
        runs.append(
            NewRun(
                model_id=item.model_id,
                variant_id=item.variant_id,
                dataset_id=body.dataset_id,
                dataset_version=body.dataset_version,
                device_id=body.device_id,
                params=body.params,
            )
        )
    with Session(s.engine) as session:
        prepared = [prepare_run(session, r) for r in runs]  # raises a 422 naming the problem before anything is made
        first = prepared[0]
        experiment = Experiment(
            name=body.name.strip(),
            notes=body.notes.strip(),
            dataset_id=first.dataset.id,
            dataset_version_id=first.version.id,
            device_id=first.device.id,
            params=body.params.model_dump(),
        )
        session.add(experiment)
        session.commit()
        session.refresh(experiment)
        assert experiment.id is not None
        experiment_id = experiment.id
    for r in runs:
        create_run(s, r, experiment_id)
    s.publish({"type": "run.updated", "id": experiment_id})
    with Session(s.engine) as session:
        return _out(s, session, _experiment_or_404(session, experiment_id), with_runs=True)


@router.post("/api/experiments/{experiment_id}/cancel", dependencies=guarded)
def cancel_experiment(experiment_id: int, request: Request) -> ExperimentOut:
    """Stop every run of the experiment that is still waiting or running."""
    s = services(request)
    with Session(s.engine) as session:
        _experiment_or_404(session, experiment_id)
        stopped = [cancel_one(s, r) for r in session.exec(select(Run).where(Run.experiment_id == experiment_id))]
    if not any(stopped):
        raise HTTPException(409, "Every run of this experiment has already finished.")
    s.publish({"type": "run.updated", "id": experiment_id})
    with Session(s.engine) as session:
        return _out(s, session, _experiment_or_404(session, experiment_id), with_runs=True)


@router.delete("/api/experiments/{experiment_id}", status_code=204, dependencies=guarded)
def remove_experiment(experiment_id: int, request: Request) -> Response:
    """Remove an experiment and all its runs. Runs still waiting or running are cancelled first."""
    s = services(request)
    with Session(s.engine) as session:
        e = _experiment_or_404(session, experiment_id)
        runs = list(session.exec(select(Run).where(Run.experiment_id == experiment_id)).all())
        for r in runs:
            job = session.get(Job, r.job_id) if r.job_id else None
            if status_of(r, job) in ACTIVE:
                cancel_one(s, r)  # a run the agent is on is asked to stop; its late result finds no run and is ignored
        for r in runs:
            session.delete(r)
        session.flush()  # the runs first: they point at the experiment
        session.delete(e)
        session.commit()
    s.publish({"type": "run.updated", "id": experiment_id})
    return Response(status_code=204)
