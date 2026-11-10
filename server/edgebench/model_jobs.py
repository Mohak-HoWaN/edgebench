"""Job handlers for models: read the model card, and convert one cell of the matrix.

A conversion that fails is an *outcome*, not an error: the cell ends in ``failed`` or ``unavailable`` with the
reason and the log, the job finishes normally, and the other cells are unaffected. Only a bug in this code raises,
and even then the cell is first moved out of ``converting`` so it can never be left looking busy.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

from sqlmodel import Session, col, select

from . import queue
from .matrix import BY_NAME, OPS, Op, cache_key, settings_for, settings_key
from .models import Artifact, MlModel, Variant, utcnow
from .services import Services
from .worker import Cancelled, Handler, JobContext, PermanentError, register

LOG_FLUSH_SECONDS = 1.5
LOG_KEEP = 64_000  # characters of converter output kept per cell, from the end
RETRYABLE = ("failed", "unavailable", "cancelled")


def _publish_model(s: Services, model_id: int) -> None:
    s.publish({"type": "model.updated", "id": model_id})


def _publish_variant(s: Services, variant: Variant) -> None:
    s.publish({"type": "variant.updated", "id": variant.id, "model_id": variant.model_id, "state": variant.state})


def _set_variant(s: Services, variant_id: int, **fields: Any) -> Variant:
    with Session(s.engine) as session:
        v = session.get(Variant, variant_id)
        if v is None:
            raise PermanentError(f"variant {variant_id} no longer exists")
        for key, value in fields.items():
            setattr(v, key, value)
        v.updated_at = utcnow()
        session.add(v)
        session.commit()
        session.refresh(v)
    _publish_variant(s, v)
    return v


def _set_model(s: Services, model_id: int, **fields: Any) -> None:
    with Session(s.engine) as session:
        m = session.get(MlModel, model_id)
        if m is None:
            raise PermanentError(f"model {model_id} no longer exists")
        for key, value in fields.items():
            setattr(m, key, value)
        session.add(m)
        session.commit()
    _publish_model(s, model_id)


def register_artifact(session: Session, sha: str, kind: str, size: int) -> None:
    if session.get(Artifact, sha) is None:
        session.add(Artifact(sha256=sha, kind=kind, size=size))


def ensure_matrix(s: Services, model_id: int) -> list[int]:
    """Create the missing cells and queue every cell not already ready or in progress. Returns the queued ids."""
    toolchain = s.converter.info().fingerprint
    to_queue: list[int] = []
    with Session(s.engine) as session:
        model = session.get(MlModel, model_id)
        if model is None or model.archived or model.status != "ready" or not model.artifact_sha256 or not model.imgsz:
            return []
        for op in OPS:
            settings = settings_for(op)
            key = settings_key(settings)
            existing = session.exec(
                select(Variant).where(
                    Variant.model_id == model_id,
                    Variant.op == op.name,
                    Variant.imgsz == model.imgsz,
                    Variant.settings_key == key,
                )
            ).first()
            ck = cache_key(model.artifact_sha256, op, model.imgsz, settings, toolchain)
            if existing is None:
                existing = Variant(
                    model_id=model_id,
                    op=op.name,
                    format=op.format,
                    precision=op.precision,
                    imgsz=model.imgsz,
                    settings=settings,
                    settings_key=key,
                    cache_key=ck,
                )
            elif existing.state in ("ready", "pending", "converting"):
                continue
            existing.cache_key = ck
            existing.state, existing.error, existing.mismatch, existing.cached = "pending", None, False, False
            existing.updated_at = utcnow()
            session.add(existing)
            session.flush()
            if existing.id is not None:
                to_queue.append(existing.id)
        session.commit()
    for variant_id in to_queue:  # queue after the commit: the queue writes through its own connection
        job_id = queue.enqueue(s.engine, "convert", {"variant_id": variant_id})
        _set_variant(s, variant_id, job_id=job_id)
    return to_queue


def add_variant(s: Services, model_id: int, op_name: str, imgsz: int, simplify: bool = True) -> list[int]:
    """Add one custom cell (another input size, or an unsimplified ONNX export) and, if it is built from another cell,
    that cell too. Cells that already exist are left alone unless they failed. Returns the queued ids."""
    op = BY_NAME[op_name]
    chain: list[Op] = []
    step: Op | None = op
    while step is not None:
        chain.insert(0, step)
        step = BY_NAME[step.needs] if step.needs else None
    toolchain = s.converter.info().fingerprint
    to_queue: list[int] = []
    with Session(s.engine) as session:
        model = session.get(MlModel, model_id)
        if model is None or model.archived or model.status != "ready" or not model.artifact_sha256:
            return []
        for cell in chain:
            settings = settings_for(cell)
            if cell is op and cell.name == "onnx_fp32":
                settings = {"simplify": simplify}
            key = settings_key(settings)
            existing = session.exec(
                select(Variant).where(
                    Variant.model_id == model_id,
                    Variant.op == cell.name,
                    Variant.imgsz == imgsz,
                    Variant.settings_key == key,
                )
            ).first()
            if existing is not None and existing.state in ("ready", "pending", "converting"):
                continue
            ck = cache_key(model.artifact_sha256, cell, imgsz, settings, toolchain)
            variant = existing or Variant(
                model_id=model_id,
                op=cell.name,
                format=cell.format,
                precision=cell.precision,
                imgsz=imgsz,
                settings=settings,
                settings_key=key,
            )
            variant.cache_key, variant.state, variant.error = ck, "pending", None
            variant.mismatch, variant.cached, variant.updated_at = False, False, utcnow()
            session.add(variant)
            session.flush()
            if variant.id is not None:
                to_queue.append(variant.id)
        session.commit()
    for variant_id in to_queue:
        job_id = queue.enqueue(s.engine, "convert", {"variant_id": variant_id})
        _set_variant(s, variant_id, job_id=job_id)
    _publish_model(s, model_id)
    return to_queue


def retry_variant(s: Services, variant_id: int) -> bool:
    toolchain = s.converter.info().fingerprint
    with Session(s.engine) as session:
        v = session.get(Variant, variant_id)
        model = session.get(MlModel, v.model_id) if v else None
        if v is None or model is None or model.archived or not model.artifact_sha256 or v.state not in RETRYABLE:
            return False
        # The converter may have been set up or upgraded since this cell was made: the key must name the toolchain that
        # runs now (ADR 0002).
        v.cache_key = cache_key(model.artifact_sha256, BY_NAME[v.op], v.imgsz, v.settings, toolchain)
        v.state, v.error, v.mismatch, v.cached, v.log = "pending", None, False, False, None
        v.updated_at = utcnow()
        session.add(v)
        session.commit()
    job_id = queue.enqueue(s.engine, "convert", {"variant_id": variant_id})
    _set_variant(s, variant_id, job_id=job_id)
    return True


def cancel_variant(s: Services, variant_id: int) -> bool:
    """Stop a waiting or running cell. Returns False if it was neither.

    A running conversion is told to stop and ends itself. A cell whose job has not started has nothing that will
    update it, so it is marked cancelled here.
    """
    with Session(s.engine) as session:
        v = session.get(Variant, variant_id)
        if v is None or v.state not in ("pending", "converting") or v.job_id is None:
            return False
        job_id = v.job_id
    if queue.request_cancel(s.engine, job_id) == "cancelled":
        _set_variant(s, variant_id, state="cancelled", error="Cancelled.")
    return True


def _requeue_dependents(s: Services, model_id: int, parent_op: str) -> None:
    """Cells that failed because their source (ONNX FP32) was missing get another go once it exists."""
    with Session(s.engine) as session:
        waiting = [
            v.id
            for v in session.exec(
                select(Variant).where(Variant.model_id == model_id, col(Variant.state) == "failed")
            ).all()
            if v.id is not None and BY_NAME[v.op].needs == parent_op and (v.error or "").startswith("Needs ")
        ]
    for variant_id in waiting:
        retry_variant(s, variant_id)


def _find_cached(s: Services, v: Variant) -> Variant | None:
    with Session(s.engine) as session:
        for hit in session.exec(
            select(Variant).where(Variant.cache_key == v.cache_key, col(Variant.state) == "ready")
        ).all():
            if hit.id != v.id and s.store.exists(hit.artifact_sha256):
                return hit
    return None


def _source_for(s: Services, v: Variant) -> tuple[Path | None, str | None]:
    """The ONNX FP32 file a dependent cell is built from, or (None, the reason it is not available)."""
    needs = BY_NAME[v.op].needs
    if needs is None:
        return None, None
    with Session(s.engine) as session:
        parent = session.exec(
            select(Variant).where(
                Variant.model_id == v.model_id,
                Variant.op == needs,
                Variant.imgsz == v.imgsz,
                Variant.settings_key
                == settings_key(settings_for(BY_NAME[needs])),  # the default export, not an experiment
            )
        ).first()
    label = BY_NAME[needs].label
    if parent is None or parent.state != "ready" or not parent.artifact_sha256 or not parent.main_file:
        return None, f"Needs {label}, which is {parent.state if parent else 'missing'}. Convert that first."
    path = s.store.path(parent.artifact_sha256) / parent.main_file
    return (path, None) if path.is_file() else (None, f"Needs {label}, but its file is gone from the store.")


def make_inspect_handler(s: Services) -> Handler:
    def inspect_job(ctx: JobContext) -> dict[str, Any]:
        model_id = int(ctx.params["model_id"])
        with Session(s.engine) as session:
            model = session.get(MlModel, model_id)
            sha = model.artifact_sha256 if model else None
            removed = bool(model and model.archived)
        if sha is None:
            raise PermanentError(f"model {model_id} has no file")
        if removed:
            return {"skipped": "the model was removed"}
        info = s.converter.info()
        if not info.available:
            _set_model(s, model_id, status="converter_missing", error=info.message)
            return {"status": "converter_missing"}
        _set_model(s, model_id, status="inspecting", error=None)
        outcome = s.converter.run_inspect(s.store.path(sha))
        card = outcome.result
        if outcome.reason == "timeout":
            _set_model(s, model_id, status="rejected", error="Reading the model took too long, so it was stopped.")
            return {"status": "rejected"}
        if card is None or not card.get("ok"):
            reason = (card or {}).get("error") or (
                outcome.log.strip().splitlines() or ["The model could not be read."]
            )[-1]
            _set_model(s, model_id, status="rejected", error=f"This file could not be read as a model: {reason}")
            return {"status": "rejected"}
        _set_model(
            s,
            model_id,
            status="ready",
            error=None,
            task=card["task"],
            imgsz=card["imgsz"],
            parameters=card["parameters"],
            gflops=card["gflops"],
            class_names=card["class_names"],
        )
        ensure_matrix(s, model_id)
        return {"status": "ready", "variants": len(OPS)}

    return inspect_job


class _Conversion:
    """One run of a ``convert`` job: a cell of the matrix, its model file, and the converter process."""

    def __init__(self, s: Services, ctx: JobContext, variant: Variant, model_sha: str) -> None:
        assert variant.id is not None
        self.s, self.ctx, self.v, self.model_sha, self.id = s, ctx, variant, model_sha, variant.id
        self.op = BY_NAME[variant.op]
        self.lines: list[str] = []
        self._last_flush = time.monotonic()

    def _set(self, **fields: Any) -> Variant:
        return _set_variant(self.s, self.id, **fields)

    def _on_line(self, line: str) -> None:
        self.lines.append(line)
        if time.monotonic() - self._last_flush > LOG_FLUSH_SECONDS:  # a live log for the drawer while it converts
            self._last_flush = time.monotonic()
            self._set(log="\n".join(self.lines)[-LOG_KEEP:])

    def run(self) -> dict[str, Any]:
        hit = _find_cached(self.s, self.v)
        if hit is not None:
            self._set(
                state="ready",
                cached=True,
                artifact_sha256=hit.artifact_sha256,
                main_file=hit.main_file,
                size_bytes=hit.size_bytes,
                seconds=hit.seconds,
                verify=hit.verify,
                mismatch=hit.mismatch,
                log="Reused an identical earlier conversion; nothing was run.",
            )
            return {"state": "ready", "cached": True}
        info = self.s.converter.info()
        if not info.available:
            self._set(state="unavailable", error=info.message)
            return {"state": "unavailable"}
        source, why_not = _source_for(self.s, self.v)
        if why_not is not None:
            self._set(state="failed", error=why_not)
            return {"state": "failed"}
        workdir = self.s.store.new_workdir()
        try:
            return self._convert(workdir, source)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)  # already moved into the store on success; this is then a no-op

    def _convert(self, workdir: Path, source: Path | None) -> dict[str, Any]:
        s = self.s
        outcome = s.converter.run_convert(
            op=self.op.name,
            pt=s.store.path(self.model_sha),
            out=workdir,
            imgsz=self.v.imgsz,
            source=source,
            simplify=bool(self.v.settings.get("simplify", True)),
            cancelled=lambda: queue.cancel_requested(s.engine, self.ctx.job) or self.ctx.lost.is_set(),
            on_line=self._on_line,
        )
        log = outcome.log[-LOG_KEEP:]
        if outcome.reason == "cancelled":
            self._set(state="cancelled", error="Cancelled.", log=log)
            raise Cancelled
        if outcome.reason == "timeout":
            minutes = s.settings.converter_timeout_seconds / 60
            self._set(state="failed", error=f"Stopped after {minutes:g} minutes without finishing.", log=log)
            return {"state": "failed"}
        result = outcome.result
        if result is None or not result.get("ok"):
            kind = (result or {}).get("kind", "failed")
            reason = (result or {}).get("error") or "The converter stopped without a result."
            self._set(state="unavailable" if kind == "unavailable" else "failed", error=reason, log=log)
            return {"state": kind}
        sha, size = s.store.put_directory(workdir)
        with Session(s.engine) as session:
            register_artifact(session, sha, "bundle", size)
            session.commit()
        check = result.get("verify") or {}
        self._set(
            state="ready",
            artifact_sha256=sha,
            main_file=result["main"],
            size_bytes=size,
            seconds=result["seconds"],
            verify=check,
            mismatch=not check.get("ok", False),
            log=log,
        )
        return {"state": "ready"}


def make_convert_handler(s: Services) -> Handler:
    def convert_job(ctx: JobContext) -> dict[str, Any]:
        variant_id = int(ctx.params["variant_id"])
        with Session(s.engine) as session:
            v = session.get(Variant, variant_id)
            model = session.get(MlModel, v.model_id) if v else None
            if v is None or model is None or not model.artifact_sha256:
                raise PermanentError("the model or the cell no longer exists")
            if v.state == "ready":
                return {"skipped": "already converted"}
            removed = model.archived
            model_sha, model_id, op_name = model.artifact_sha256, v.model_id, v.op
        if removed:
            _set_variant(s, variant_id, state="cancelled", error="The model was removed.")
            return {"skipped": "the model was removed"}
        v = _set_variant(s, variant_id, state="converting", error=None, mismatch=False, cached=False, log=None)
        try:
            outcome = _Conversion(s, ctx, v, model_sha).run()
        except (Cancelled, PermanentError):
            raise
        except Exception as exc:
            # A bug here must not leave the cell looking busy forever.
            _set_variant(s, variant_id, state="failed", error=f"Internal error: {type(exc).__name__}: {exc}")
            raise PermanentError(str(exc)) from exc
        if outcome.get("state") == "ready" and op_name == "onnx_fp32":
            _requeue_dependents(s, model_id, "onnx_fp32")
        return outcome

    return convert_job


def register_handlers(s: Services) -> None:
    register("inspect")(make_inspect_handler(s))
    register("convert")(make_convert_handler(s))
