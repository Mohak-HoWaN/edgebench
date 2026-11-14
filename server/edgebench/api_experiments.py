"""Experiments: a named group of runs that share a dataset version, a device and settings.

An experiment is one model variant per run, or a sweep: every combination of variant, thread count, pinned CPUs and
input size (Phase 4). The plan endpoint shows what a sweep would run (and what it leaves out, with the reason) before
anything starts.
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from . import drift as drifting
from . import latency, sweep
from .api_models import services
from .api_runs import (
    BASELINE_LABEL,
    NewRun,
    RunOut,
    RunParams,
    cancel_one,
    cell_label,
    create_run,
    prepare_run,
    run_out,
    status_of,
)
from .models import Dataset, DatasetVersion, Device, Experiment, Job, MlModel, Run, Variant
from .security import same_origin
from .services import Services

router = APIRouter()
guarded = [Depends(same_origin)]
ACTIVE = ("queued", "running")
REPLACEABLE = (
    "cancelled",
    "lost",
)  # resuming makes these again; finished, failed and "unavailable" runs are never repeated


class Item(BaseModel):
    model_id: int
    variant_id: int | None = None  # None: the .pt baseline


class Sweep(BaseModel):
    """Axes to vary. An empty axis means "as the base settings say"; the runs are every combination of the axes."""

    threads: list[Annotated[int, Field(ge=1, le=1024)]] = Field(default_factory=list, max_length=16)
    cpu_sets: list[Annotated[list[int], Field(max_length=1024)]] = Field(default_factory=list, max_length=16)
    imgsz: list[Annotated[int, Field(ge=32, le=2048, multiple_of=32)]] = Field(default_factory=list, max_length=8)


class NewExperiment(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    notes: str = Field(default="", max_length=4000)
    dataset_id: int
    dataset_version: int | None = None
    device_id: int
    params: RunParams = RunParams()
    items: list[Item] = Field(min_length=1, max_length=200)
    sweep: Sweep = Sweep()


class PlannedRun(BaseModel):
    label: str
    threads: int
    cpu_list: list[int] | None
    imgsz: int
    estimated_seconds: float
    guessed: bool  # True: nothing on this device has been measured for this conversion, so the time is a guess


class PrunedRun(BaseModel):
    label: str
    threads: int
    cpu_list: list[int] | None
    imgsz: int
    reason: str


class PlanOut(BaseModel):
    runs: list[PlannedRun]
    pruned: list[PrunedRun]
    run_count: int
    estimated_seconds: float
    guessed_runs: int
    images: int
    repeats: int


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
    resumable: bool  # some runs were cancelled or lost and the experiment remembers its plan
    comparisons: dict[
        int, dict[str, Any]
    ]  # run id -> speed-up and Welch's test against the baseline at the same settings
    drift: dict[int, dict[str, Any]]  # run id -> drift from the .pt baseline, with the pass or fail verdict
    runs: list[RunOut] | None = None


def limits_from(max_map_drop: float | None, min_agreement: float | None) -> drifting.Thresholds:
    d = drifting.DEFAULT_THRESHOLDS
    return drifting.Thresholds(
        d.max_map_drop if max_map_drop is None else max_map_drop,
        d.min_agreement if min_agreement is None else min_agreement,
    )


@lru_cache(maxsize=8)
def _predictions(path: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    return data


_DRIFT: dict[
    tuple[int, int, str | None, str | None], dict[str, Any]
] = {}  # finished runs never change (a rerun is a new run)


def _drift_numbers(s: Services, base: Run, run: Run, base_names: list[str], names: list[str]) -> dict[str, Any]:
    assert base.id is not None and run.id is not None
    base_sha, sha = (base.result or {}).get("predictions_sha"), (run.result or {}).get("predictions_sha")
    key = (base.id, run.id, base_sha, sha)
    if key not in _DRIFT:
        base_p = (
            _predictions(str(s.store.path(base_sha)))["pictures"] if base_sha and s.store.exists(base_sha) else None
        )
        p = _predictions(str(s.store.path(sha)))["pictures"] if sha and s.store.exists(sha) else None
        if len(_DRIFT) > 2000:
            _DRIFT.clear()
        _DRIFT[key] = drifting.measure(
            base_p,
            p,
            base_names,
            names,
            base_accuracy=(base.result or {}).get("accuracy"),
            other_accuracy=(run.result or {}).get("accuracy"),
        )
    return _DRIFT[key]


def _config_key(run: Run) -> tuple[int | None, int, tuple[int, ...]]:
    params = run.params or {}
    return (run.variant_id, int(params.get("threads", 0)), tuple(sorted(params.get("cpu_list") or ())))


def _comparisons_and_drift(
    s: Services, session: Session, runs: list[Run], outs: dict[int, RunOut], limits: drifting.Thresholds
) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]]]:
    """Each converted run against the .pt baseline of the same model: speed-up at the same settings, and drift."""
    done = [r for r in runs if r.id is not None and outs[r.id].status == "done" and r.result]
    comparisons: dict[int, dict[str, Any]] = {}
    drifts: dict[int, dict[str, Any]] = {}
    baselines = [r for r in done if r.variant_id is None]
    if not baselines:
        return comparisons, drifts
    same_settings = {
        (b.model_id, *_config_key(b)[1:]): b for b in reversed(baselines)
    }  # the earliest baseline wins a tie
    first_of = {b.model_id: b for b in reversed(baselines)}
    names: dict[int | None, list[str]] = {}

    def class_names(r: Run) -> list[str]:
        if r.model_id not in names:
            model = session.get(MlModel, r.model_id) if r.model_id else None
            names[r.model_id] = list(model.class_names or []) if model else []
        return names[r.model_id]

    for r in done:
        if r.variant_id is None or r.id is None:
            continue
        ref = same_settings.get((r.model_id, *_config_key(r)[1:]))
        if ref is not None:
            c = latency.compare((ref.result or {}).get("speed"), (r.result or {}).get("speed"))
            if c is not None:
                comparisons[r.id] = {**c, "vs_run_id": ref.id}
        base = first_of.get(r.model_id)
        if base is not None:
            numbers = _drift_numbers(s, base, r, class_names(base), class_names(r))
            drifts[r.id] = {**numbers, "baseline_run_id": base.id, "verdict": drifting.verdict(numbers, limits)}
    return comparisons, drifts


def _out(s: Services, session: Session, e: Experiment, with_runs: bool, limits: drifting.Thresholds) -> ExperimentOut:
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
    comparisons, drifts = _comparisons_and_drift(s, session, runs, {o.id: o for o in outs}, limits)
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
        resumable=bool(e.plan) and status != "running" and any(o.status in REPLACEABLE for o in outs),
        comparisons=comparisons,
        drift=drifts,
        runs=outs if with_runs else None,
    )


def _experiment_or_404(session: Session, experiment_id: int) -> Experiment:
    e = session.get(Experiment, experiment_id)
    if e is None:
        raise HTTPException(404, "There is no such experiment.")
    return e


@router.get("/api/experiments")
def list_experiments(
    request: Request, max_map_drop: float | None = None, min_agreement: float | None = None
) -> list[ExperimentOut]:
    """Every experiment, each with its runs (the Results page shows the best of them in one row)."""
    s = services(request)
    limits = limits_from(max_map_drop, min_agreement)
    with Session(s.engine) as session:
        rows = session.exec(select(Experiment).order_by(col(Experiment.id).desc()))
        return [_out(s, session, e, True, limits) for e in rows]


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
                    "threads": (r.params or {}).get("threads"),
                    "cpu_list": (r.params or {}).get("cpu_list"),
                    "status": ro.status,
                    "class_names": model.class_names if model else [],
                    "detections": pictures.get(str(image)) if pictures is not None else None,
                }
            )
    return {"image": image, "runs": out}


@router.get("/api/experiments/{experiment_id}")
def get_experiment(
    experiment_id: int, request: Request, max_map_drop: float | None = None, min_agreement: float | None = None
) -> ExperimentOut:
    s = services(request)
    with Session(s.engine) as session:
        e = _experiment_or_404(session, experiment_id)
        return _out(s, session, e, True, limits_from(max_map_drop, min_agreement))


# --- sweeps ----------------------------------------------------------------------------------------------------------


def _subjects(session: Session, items: list[Item]) -> list[sweep.Subject]:
    """The distinct things picked, each with the input sizes its conversion exists at."""
    out: list[sweep.Subject] = []
    seen: set[tuple[int, int | None]] = set()
    for item in items:
        if (item.model_id, item.variant_id) in seen:
            continue
        seen.add((item.model_id, item.variant_id))
        model = session.get(MlModel, item.model_id)
        if model is None or model.archived or model.status != "ready":
            raise HTTPException(422, "That model is not ready to run.")
        if item.variant_id is None:
            out.append(sweep.Subject(model.id or 0, None, BASELINE_LABEL, model.imgsz or 640, {}))
            continue
        variant = session.get(Variant, item.variant_id)
        if variant is None or variant.model_id != model.id:
            raise HTTPException(422, "That conversion does not belong to this model.")
        siblings = session.exec(
            select(Variant).where(
                Variant.model_id == model.id,
                Variant.op == variant.op,
                Variant.settings_key == variant.settings_key,
                Variant.state == "ready",
            )
        ).all()
        sizes = {v.imgsz: v.id or 0 for v in siblings if v.artifact_sha256}
        label = cell_label(variant)
        out.append(sweep.Subject(model.id or 0, variant.id, label, variant.imgsz, sizes))
    return out


def _expand(session: Session, body: NewExperiment) -> tuple[list[sweep.Config], list[sweep.Pruned]]:
    device = session.get(Device, body.device_id)
    if device is None or device.revoked or device.token_hash is None:
        raise HTTPException(422, "That device has not connected an agent yet.")
    logical = (device.fingerprint or {}).get("logical_cores")
    axes = body.sweep
    kept, pruned = sweep.expand(
        _subjects(session, body.items),
        axes.threads or [body.params.threads],
        axes.cpu_sets or [body.params.cpu_list],
        axes.imgsz or [None],
        logical if isinstance(logical, int) and logical > 0 else None,
    )
    if not kept:
        why = "; ".join(sorted({f"{p.label}: {p.reason}" for p in pruned})[:3])
        raise HTTPException(422, f"Every combination was left out. {why}")
    if len(kept) > sweep.MAX_RUNS:
        raise HTTPException(422, f"That is {len(kept)} runs; the most one experiment can have is {sweep.MAX_RUNS}.")
    return kept, pruned


def _run_for(body: NewExperiment, c: sweep.Config) -> NewRun:
    return NewRun(
        model_id=c.subject.model_id,
        variant_id=c.variant_id,
        dataset_id=body.dataset_id,
        dataset_version=body.dataset_version,
        device_id=body.device_id,
        params=body.params.model_copy(
            update={"threads": c.threads, "cpu_list": list(c.cpu_list) if c.cpu_list else None}
        ),
    )


def _earlier_ms(session: Session, c: sweep.Config, device_id: int) -> float | None:
    """The median inference time of earlier finished runs of this conversion on this device, if there are any."""
    query = select(Run).where(Run.device_id == device_id, Run.outcome == "done", Run.model_id == c.subject.model_id)
    query = (
        query.where(Run.variant_id == c.variant_id)
        if c.variant_id is not None
        else query.where(col(Run.variant_id).is_(None))
    )
    values = [
        x["p50_ms"]
        for r in session.exec(query.order_by(col(Run.id).desc()).limit(20))
        if (x := latency.summary((r.result or {}).get("speed")))
    ]
    return sweep.median(values)


@router.post("/api/experiments/plan")
def plan_experiment(body: NewExperiment, request: Request) -> PlanOut:
    """What the experiment would run and how long it should take, without starting anything."""
    s = services(request)
    with Session(s.engine) as session:
        configs, pruned = _expand(session, body)
        prepared = prepare_run(
            session, _run_for(body, configs[0]), s.converter.info().versions
        )  # the first run stands for the dataset and device checks
        images = prepared.version.image_count
        if body.params.max_images:
            images = min(images, body.params.max_images)
        history: dict[int | None, float | None] = {}
        planned: list[PlannedRun] = []
        for c in configs:
            if c.variant_id not in history:
                history[c.variant_id] = _earlier_ms(session, c, body.device_id)
            ms = history[c.variant_id]
            p = body.params
            seconds = sweep.seconds_for_run(
                images, ms or sweep.GUESS_MS, p.warmup, p.iterations, p.repeats, accuracy=p.accuracy
            )
            planned.append(
                PlannedRun(
                    label=c.label,
                    threads=c.threads,
                    cpu_list=list(c.cpu_list) if c.cpu_list else None,
                    imgsz=c.imgsz,
                    estimated_seconds=round(seconds, 1),
                    guessed=ms is None,
                )
            )
    return PlanOut(
        runs=planned,
        pruned=[
            PrunedRun(
                label=x.label,
                threads=x.threads,
                cpu_list=list(x.cpu_list) if x.cpu_list else None,
                imgsz=x.imgsz,
                reason=x.reason,
            )
            for x in pruned
        ],
        run_count=len(planned),
        estimated_seconds=round(sum(r.estimated_seconds for r in planned), 1),
        guessed_runs=sum(r.guessed for r in planned),
        images=images,
        repeats=body.params.repeats,
    )


@router.post("/api/experiments", status_code=201, dependencies=guarded)
def start_experiment(body: NewExperiment, request: Request) -> ExperimentOut:
    """Create the experiment and queue its runs. Everything is checked first: all runs start or none do."""
    s = services(request)
    with Session(s.engine) as session:
        configs, _ = _expand(session, body)
        runs = [_run_for(body, c) for c in configs]
        versions = s.converter.info().versions
        prepared = [
            prepare_run(session, r, versions) for r in runs
        ]  # raises a 422 naming the problem before anything is made
        first = prepared[0]
        experiment = Experiment(
            name=body.name.strip(),
            notes=body.notes.strip(),
            dataset_id=first.dataset.id,
            dataset_version_id=first.version.id,
            device_id=first.device.id,
            params=body.params.model_dump(),
            plan={
                "items": [i.model_dump() for i in body.items],
                "sweep": body.sweep.model_dump(),
            },
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
        return _out(s, session, _experiment_or_404(session, experiment_id), True, drifting.DEFAULT_THRESHOLDS)


@router.post("/api/experiments/{experiment_id}/resume", dependencies=guarded)
def resume_experiment(experiment_id: int, request: Request) -> ExperimentOut:
    """Make the runs a cancelled (or interrupted) sweep never finished. Runs that finished, failed or are still going
    are left alone: nothing is measured twice, and a run that failed is repeated with its own Run again button."""
    s = services(request)
    with Session(s.engine) as session:
        e = _experiment_or_404(session, experiment_id)
        if not e.plan:
            raise HTTPException(
                409, "This experiment was made before experiments remembered their plan, so it cannot be resumed."
            )
        version = session.get(DatasetVersion, e.dataset_version_id) if e.dataset_version_id else None
        if version is None or e.dataset_id is None or e.device_id is None:
            raise HTTPException(409, "The dataset or the device of this experiment is gone.")
        body = NewExperiment(
            name=e.name,
            dataset_id=e.dataset_id,
            dataset_version=version.number,
            device_id=e.device_id,
            params=RunParams(**(e.params or {})),
            items=[Item(**i) for i in e.plan["items"]],
            sweep=Sweep(**e.plan["sweep"]),
        )
        configs, _ = _expand(session, body)
        existing = list(session.exec(select(Run).where(Run.experiment_id == experiment_id)).all())
        status = {r.id: status_of(r, session.get(Job, r.job_id) if r.job_id else None) for r in existing}
        if any(s in ACTIVE for s in status.values()):
            # a run that was asked to stop is still "running" until its agent notices (its next heartbeat)
            raise HTTPException(
                409, "Some runs are still going or stopping. Wait until they have stopped, then resume."
            )
        keep = {_config_key(r) for r in existing if status[r.id] not in REPLACEABLE}
        todo = [c for c in configs if c.key not in keep]
        if not todo:
            raise HTTPException(409, "Every run of this experiment has been made already.")
        redo = {c.key for c in todo}
        runs = [_run_for(body, c) for c in todo]
        for r in runs:
            prepare_run(session, r, s.converter.info().versions)
        for old in existing:
            if status[old.id] in REPLACEABLE and _config_key(old) in redo:
                session.delete(old)  # a cancelled or lost run has no result; the new run takes its place
        session.commit()
    for r in runs:
        create_run(s, r, experiment_id)
    s.publish({"type": "run.updated", "id": experiment_id})
    with Session(s.engine) as session:
        return _out(s, session, _experiment_or_404(session, experiment_id), True, drifting.DEFAULT_THRESHOLDS)


@router.post("/api/experiments/{experiment_id}/cancel", dependencies=guarded)
def cancel_experiment(experiment_id: int, request: Request) -> ExperimentOut:
    """Stop every run of the experiment that is still waiting or running. Runs that finished keep their results."""
    s = services(request)
    with Session(s.engine) as session:
        _experiment_or_404(session, experiment_id)
        stopped = [cancel_one(s, r) for r in session.exec(select(Run).where(Run.experiment_id == experiment_id))]
    if not any(stopped):
        raise HTTPException(409, "Every run of this experiment has already finished.")
    s.publish({"type": "run.updated", "id": experiment_id})
    with Session(s.engine) as session:
        return _out(s, session, _experiment_or_404(session, experiment_id), True, drifting.DEFAULT_THRESHOLDS)


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
