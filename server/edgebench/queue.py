"""SQLite-backed job queue (ADR 0001).

Every state change is one SQL statement, so two workers can never claim the same job. A claimed or running job keeps
``heartbeat_at`` fresh; ``requeue_stale`` returns jobs whose worker vanished. Calls that finish a job carry the
``Claimed`` handle and apply only while the job is still on that attempt, so a worker presumed dead cannot overwrite
a retry.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, cast

from sqlalchemy import Engine, Table, case, false, func, inspect, literal, null, select, update
from sqlmodel import Session

from .models import Job, utcnow

# Core table: statements below run on the connection so SQLModel's UTC column type applies to timestamps.
_t = cast(Table, inspect(Job).local_table)
ACTIVE = ("claimed", "running")
# Jobs an agent on a device runs; the server's own worker must never take them.
AGENT_JOB_TYPES = ("benchmark",)


@dataclass(frozen=True)
class Claimed:
    id: int
    type: str
    params: dict[str, Any]
    attempts: int
    max_attempts: int


def enqueue(
    engine: Engine,
    job_type: str,
    params: dict[str, Any] | None = None,
    *,
    priority: int = 0,
    max_attempts: int = 3,
    device_id: int | None = None,
) -> int:
    """Add a job. Lower ``priority`` runs first; equal priority runs in the order added."""
    with Session(engine) as session:
        job = Job(type=job_type, params=params or {}, priority=priority, max_attempts=max_attempts, device_id=device_id)
        session.add(job)
        session.commit()
        session.refresh(job)
        if job.id is None:
            raise RuntimeError("job was not assigned an id")
        return job.id


def claim(engine: Engine, worker: str, *, device_id: int | None = None) -> Claimed | None:
    """Atomically take the next queued job, or return None.

    The server's worker (no ``device_id``) takes jobs that are not agent jobs; an agent passes its device id and takes
    only the agent jobs queued for that device.
    """
    now = utcnow()
    wanted = (
        (_t.c.type.in_(AGENT_JOB_TYPES) & (_t.c.device_id == device_id))
        if device_id is not None
        else _t.c.type.not_in(AGENT_JOB_TYPES)
    )
    next_id = (
        select(_t.c.id)
        .where((_t.c.state == "queued") & wanted)
        .order_by(_t.c.priority, _t.c.id)
        .limit(1)
        .scalar_subquery()
    )
    stmt = (
        update(_t)
        .where(_t.c.id == next_id)
        .values(state="claimed", worker=worker, claimed_at=now, heartbeat_at=now, attempts=_t.c.attempts + 1)
        .returning(_t.c.id, _t.c.type, _t.c.params, _t.c.attempts, _t.c.max_attempts)
    )
    with engine.begin() as conn:
        row = conn.execute(stmt).first()
    return None if row is None else Claimed(row.id, row.type, row.params, row.attempts, row.max_attempts)


def _own(job: Claimed) -> Any:
    return (_t.c.id == job.id) & (_t.c.attempts == job.attempts) & _t.c.state.in_(ACTIVE)


def mark_running(engine: Engine, job: Claimed) -> bool:
    with engine.begin() as conn:
        done = conn.execute(
            update(_t).where(_own(job) & (_t.c.state == "claimed")).values(state="running", heartbeat_at=utcnow())
        )
    return done.rowcount == 1


def heartbeat(engine: Engine, job: Claimed) -> bool:
    with engine.begin() as conn:
        done = conn.execute(update(_t).where(_own(job)).values(heartbeat_at=utcnow()))
    return done.rowcount == 1


def complete(engine: Engine, job: Claimed, result: dict[str, Any] | None) -> bool:
    with engine.begin() as conn:
        done = conn.execute(
            update(_t).where(_own(job)).values(state="done", result=result, finished_at=utcnow(), error=None)
        )
    return done.rowcount == 1


def fail(engine: Engine, job: Claimed, error: str, *, retry: bool = True) -> str | None:
    """Record a failure. Returns the new state, or None if the job is no longer ours.

    The state is chosen inside the statement, so a cancel that arrives at the same moment is not lost: a job that was
    being cancelled ends cancelled and is not retried; otherwise it is queued again while attempts remain, else failed.
    """
    can_retry = _t.c.attempts < _t.c.max_attempts if retry else false()
    state = case((_t.c.cancel_requested, "cancelled"), (can_retry, "queued"), else_="failed")
    now = literal(utcnow(), _t.c.finished_at.type)  # typed, so SQLModel's UTC handling applies
    stmt = (
        update(_t)
        .where(_own(job))
        .values(
            state=state,
            error=error,
            worker=case((state == "queued", null()), else_=_t.c.worker),
            finished_at=case((state == "queued", null()), else_=now),
        )
        .returning(_t.c.state)
    )
    with engine.begin() as conn:
        return conn.execute(stmt).scalar()


def request_cancel(engine: Engine, job_id: int) -> str | None:
    """Cancel a queued job at once; ask an active one to stop. Returns the job's state afterwards, None if unknown."""
    with engine.begin() as conn:
        queued = conn.execute(
            update(_t)
            .where((_t.c.id == job_id) & (_t.c.state == "queued"))
            .values(state="cancelled", finished_at=utcnow())
        )
        if queued.rowcount == 0:
            conn.execute(update(_t).where((_t.c.id == job_id) & _t.c.state.in_(ACTIVE)).values(cancel_requested=True))
        return conn.execute(select(_t.c.state).where(_t.c.id == job_id)).scalar()


def cancel_requested(engine: Engine, job: Claimed) -> bool:
    with engine.connect() as conn:
        return bool(conn.execute(select(_t.c.cancel_requested).where(_t.c.id == job.id)).scalar())


def mark_cancelled(engine: Engine, job: Claimed) -> bool:
    with engine.begin() as conn:
        done = conn.execute(update(_t).where(_own(job)).values(state="cancelled", finished_at=utcnow()))
    return done.rowcount == 1


def requeue_stale(engine: Engine, stale_seconds: float) -> int:
    """Recover jobs whose worker stopped sending heartbeats: back to queued while attempts remain, otherwise lost.

    A job that was being cancelled becomes cancelled instead. Returns how many jobs were touched.
    """
    cutoff = utcnow() - timedelta(seconds=stale_seconds)
    stale = _t.c.state.in_(ACTIVE) & (_t.c.heartbeat_at < cutoff)
    with engine.begin() as conn:
        n = conn.execute(
            update(_t).where(stale & _t.c.cancel_requested).values(state="cancelled", finished_at=utcnow())
        ).rowcount
        n += conn.execute(
            update(_t)
            .where(stale & (_t.c.attempts < _t.c.max_attempts))
            .values(state="queued", worker=None, claimed_at=None)
        ).rowcount
        n += conn.execute(update(_t).where(stale).values(state="lost", finished_at=utcnow())).rowcount
    return n


def counts(engine: Engine) -> dict[str, int]:
    out = dict.fromkeys(("queued", "claimed", "running", "done", "failed", "cancelled", "lost"), 0)
    with engine.connect() as conn:
        for state, n in conn.execute(select(_t.c.state, func.count()).group_by(_t.c.state)):
            out[state] = n
    return out


def get(engine: Engine, job_id: int) -> Job | None:
    with Session(engine) as session:
        return session.get(Job, job_id)
