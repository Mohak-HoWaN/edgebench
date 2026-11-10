from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
from helpers import make_stale
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError

from edgebench import queue, worker
from edgebench.queue import Claimed
from edgebench.worker import JobContext, PermanentError, Worker

HANDLER_NAMES = ("echo", "boom", "bad", "slow", "beat", "never", "cancel-then-boom")


@pytest.fixture(autouse=True)
def _clean_handlers() -> Iterator[None]:
    yield
    for name in HANDLER_NAMES:
        worker.unregister(name)


def make_worker(engine: Engine, events: list[dict[str, Any]], *, heartbeat: float = 0.05, stale: float = 30) -> Worker:
    return Worker(engine, events.append, poll_seconds=0.02, heartbeat_seconds=heartbeat, stale_seconds=stale)


def wait_for(predicate: Any, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_a_job_runs_and_its_result_is_stored(engine: Engine) -> None:
    @worker.register("echo")
    def echo(ctx: JobContext) -> dict[str, Any]:
        return {"got": ctx.params["x"]}

    events: list[dict[str, Any]] = []
    job_id = queue.enqueue(engine, "echo", {"x": 7})
    assert make_worker(engine, events).run_once() is True
    row = queue.get(engine, job_id)
    assert row is not None and row.state == "done" and row.result == {"got": 7}
    assert [e["state"] for e in events if e["type"] == "job.state"] == ["claimed", "running", "done"]


def test_run_once_returns_false_when_nothing_is_queued(engine: Engine) -> None:
    assert make_worker(engine, []).run_once() is False


def test_an_unexpected_error_is_retried_then_fails(engine: Engine) -> None:
    calls: list[int] = []

    @worker.register("boom")
    def boom(ctx: JobContext) -> None:
        calls.append(ctx.job.attempts)
        raise RuntimeError("converter exploded")

    job_id = queue.enqueue(engine, "boom", max_attempts=3)
    w = make_worker(engine, [])
    for _ in range(4):
        w.run_once()
    row = queue.get(engine, job_id)
    assert calls == [1, 2, 3]
    assert row is not None and row.state == "failed" and "converter exploded" in (row.error or "")


def test_a_permanent_error_fails_at_once(engine: Engine) -> None:
    @worker.register("bad")
    def bad(ctx: JobContext) -> None:
        raise PermanentError("model file is not a checkpoint")

    job_id = queue.enqueue(engine, "bad", max_attempts=3)
    make_worker(engine, []).run_once()
    row = queue.get(engine, job_id)
    assert row is not None and row.state == "failed" and row.attempts == 1


def test_a_job_with_no_handler_fails_with_a_clear_message(engine: Engine) -> None:
    job_id = queue.enqueue(engine, "nobody-handles-this")
    make_worker(engine, []).run_once()
    row = queue.get(engine, job_id)
    assert row is not None and row.state == "failed" and "no handler" in (row.error or "")


def test_cancelling_a_running_job_stops_it(engine: Engine) -> None:
    started = threading.Event()

    @worker.register("slow")
    def slow(ctx: JobContext) -> None:
        started.set()
        for i in range(500):  # up to 10 s unless cancelled
            time.sleep(0.02)
            ctx.progress(i / 500)

    job_id = queue.enqueue(engine, "slow")
    w = make_worker(engine, [])
    t = threading.Thread(target=w.run_once)
    t.start()
    assert started.wait(5)
    queue.request_cancel(engine, job_id)
    t.join(timeout=5)
    assert not t.is_alive()
    row = queue.get(engine, job_id)
    assert row is not None and row.state == "cancelled"


def test_an_error_after_cancel_ends_cancelled_and_is_not_retried(engine: Engine) -> None:
    events: list[dict[str, Any]] = []

    @worker.register("cancel-then-boom")
    def cancel_then_boom(ctx: JobContext) -> None:
        queue.request_cancel(ctx.engine, ctx.job.id)  # the user pressed Cancel...
        raise RuntimeError("...and the converter then crashed")  # ...before the handler next looked at the flag

    job_id = queue.enqueue(engine, "cancel-then-boom", max_attempts=3)
    w = make_worker(engine, events)
    w.run_once()
    assert w.run_once() is False  # nothing was queued again
    row = queue.get(engine, job_id)
    assert row is not None and row.state == "cancelled" and row.attempts == 1
    assert [e["state"] for e in events if e["type"] == "job.state"][-1] == "cancelled"


def test_heartbeat_keeps_advancing_while_a_job_runs(engine: Engine) -> None:
    seen: list[Any] = []

    @worker.register("beat")
    def beat(ctx: JobContext) -> None:
        first = queue.get(ctx.engine, ctx.job.id)
        assert first is not None
        seen.append(first.heartbeat_at)
        time.sleep(0.4)
        second = queue.get(ctx.engine, ctx.job.id)
        assert second is not None
        seen.append(second.heartbeat_at)

    queue.enqueue(engine, "beat")
    make_worker(engine, [], heartbeat=0.05).run_once()
    assert seen[1] > seen[0]


def test_a_failed_heartbeat_write_does_not_stop_later_heartbeats(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A transient 'database is locked' on one heartbeat must not leave the job looking dead for the rest of its run."""
    real = queue.heartbeat
    calls: list[int] = []

    def flaky(eng: Engine, job: Claimed) -> bool:
        calls.append(1)
        if len(calls) <= 2:
            raise OperationalError("UPDATE", {}, Exception("database is locked"))
        return real(eng, job)

    monkeypatch.setattr(queue, "heartbeat", flaky)

    @worker.register("beat")
    def beat(ctx: JobContext) -> None:
        assert wait_for(lambda: len(calls) >= 4, timeout=5)  # the heartbeat thread is still beating after two failures

    job_id = queue.enqueue(engine, "beat")
    make_worker(engine, [], heartbeat=0.03).run_once()
    row = queue.get(engine, job_id)
    assert row is not None and row.state == "done"


def test_a_job_that_was_taken_over_stops_instead_of_running_twice(engine: Engine) -> None:
    started = threading.Event()
    stopped_early = threading.Event()

    @worker.register("slow")
    def slow(ctx: JobContext) -> None:
        started.set()
        for _ in range(500):
            time.sleep(0.02)
            ctx.check_cancelled()
        stopped_early.clear()

    stopped_early.set()
    job_id = queue.enqueue(engine, "slow")
    w = make_worker(engine, [], heartbeat=0.03)
    t = threading.Thread(target=w.run_once)
    t.start()
    assert started.wait(5)
    make_stale(engine, job_id)  # the sweep decides this worker is dead and puts the job back...
    assert queue.requeue_stale(engine, 60) == 1
    t.join(timeout=5)  # ...so its next heartbeat fails and the handler must stop at its next check
    assert not t.is_alive() and stopped_early.is_set()
    row = queue.get(engine, job_id)
    assert row is not None and row.state == "queued" and row.attempts == 1  # untouched by the old worker


def test_a_job_taken_over_before_it_starts_is_not_run(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[int] = []

    @worker.register("never")
    def never(ctx: JobContext) -> None:
        ran.append(1)

    monkeypatch.setattr(queue, "mark_running", lambda eng, job: False)
    queue.enqueue(engine, "never")
    assert make_worker(engine, []).run_once() is True
    assert ran == []


def test_a_restarted_worker_resumes_a_job_left_running_by_a_dead_one(engine: Engine) -> None:
    """The server was killed mid-job. The new worker's first sweep puts the job back and finishes it."""

    @worker.register("echo")
    def echo(ctx: JobContext) -> dict[str, Any]:
        return {"attempt": ctx.job.attempts}

    job_id = queue.enqueue(engine, "echo")
    dead = queue.claim(engine, "dead-worker")
    assert dead is not None
    queue.mark_running(engine, dead)
    make_stale(engine, job_id)

    w = Worker(engine, lambda e: None, poll_seconds=0.02, heartbeat_seconds=0.05, stale_seconds=60)
    w.start()
    try:
        finished = wait_for(lambda: (r := queue.get(engine, job_id)) is not None and r.state == "done")
    finally:
        w.stop()
    row = queue.get(engine, job_id)
    assert finished and row is not None and row.result == {"attempt": 2}
