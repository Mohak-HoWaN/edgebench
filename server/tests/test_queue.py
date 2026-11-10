from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

from helpers import make_stale
from sqlalchemy import Engine, text

from edgebench import queue
from edgebench.config import Settings

STALE = 60  # seconds; make_stale() back-dates by an hour, a fresh claim is seconds old


def test_claim_order_is_priority_then_age(engine: Engine) -> None:
    a = queue.enqueue(engine, "t")
    b = queue.enqueue(engine, "t", priority=-1)
    c = queue.enqueue(engine, "t")
    order = [queue.claim(engine, "w") for _ in range(3)]
    assert [j.id for j in order if j] == [b, a, c]


def test_claim_on_empty_queue_returns_none(engine: Engine) -> None:
    assert queue.claim(engine, "w") is None


def test_concurrent_workers_never_claim_the_same_job(engine: Engine) -> None:
    ids = {queue.enqueue(engine, "t") for _ in range(60)}
    taken: list[int] = []
    lock = threading.Lock()

    def drain(name: str) -> None:
        while (job := queue.claim(engine, name)) is not None:
            with lock:
                taken.append(job.id)

    threads = [threading.Thread(target=drain, args=(f"w{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(taken) == sorted(ids)  # every job exactly once


def test_failures_retry_until_attempts_run_out(engine: Engine) -> None:
    job_id = queue.enqueue(engine, "t", max_attempts=3)
    states = []
    for _ in range(3):
        job = queue.claim(engine, "w")
        assert job is not None
        states.append(queue.fail(engine, job, "boom"))
    assert states == ["queued", "queued", "failed"]
    row = queue.get(engine, job_id)
    assert row is not None and row.state == "failed" and row.attempts == 3 and row.error == "boom"
    assert row.finished_at is not None
    assert queue.claim(engine, "w") is None


def test_a_retry_clears_the_worker_and_the_finish_time(engine: Engine) -> None:
    job_id = queue.enqueue(engine, "t", max_attempts=2)
    job = queue.claim(engine, "w")
    assert job is not None
    assert queue.fail(engine, job, "boom") == "queued"
    row = queue.get(engine, job_id)
    assert row is not None and row.state == "queued" and row.worker is None and row.finished_at is None


def test_permanent_failure_is_not_retried(engine: Engine) -> None:
    queue.enqueue(engine, "t", max_attempts=3)
    job = queue.claim(engine, "w")
    assert job is not None
    assert queue.fail(engine, job, "bad input", retry=False) == "failed"


def test_a_job_that_fails_while_being_cancelled_is_cancelled_not_retried(engine: Engine) -> None:
    """The handler errored after the user pressed Cancel: the job must stay cancelled, not run again."""
    job_id = queue.enqueue(engine, "t", max_attempts=3)
    job = queue.claim(engine, "w")
    assert job is not None
    queue.request_cancel(engine, job_id)
    assert queue.fail(engine, job, "boom") == "cancelled"
    row = queue.get(engine, job_id)
    assert row is not None and row.state == "cancelled" and row.finished_at is not None
    assert queue.claim(engine, "w") is None


def test_fail_on_a_job_we_no_longer_own_changes_nothing(engine: Engine) -> None:
    queue.enqueue(engine, "t")
    job = queue.claim(engine, "w")
    assert job is not None
    queue.complete(engine, job, None)
    assert queue.fail(engine, job, "late") is None
    row = queue.get(engine, job.id)
    assert row is not None and row.state == "done" and row.error is None


def test_cancelling_a_queued_job_is_immediate(engine: Engine) -> None:
    job_id = queue.enqueue(engine, "t")
    assert queue.request_cancel(engine, job_id) == "cancelled"
    assert queue.claim(engine, "w") is None


def test_cancelling_a_running_job_sets_a_flag_the_job_can_see(engine: Engine) -> None:
    queue.enqueue(engine, "t")
    job = queue.claim(engine, "w")
    assert job is not None and not queue.cancel_requested(engine, job)
    assert queue.request_cancel(engine, job.id) == "claimed"
    assert queue.cancel_requested(engine, job)


def test_request_cancel_on_unknown_or_finished_job(engine: Engine) -> None:
    assert queue.request_cancel(engine, 999) is None
    queue.enqueue(engine, "t")
    job = queue.claim(engine, "w")
    assert job is not None
    queue.complete(engine, job, {"ok": True})
    assert queue.request_cancel(engine, job.id) == "done"


def test_stale_job_goes_back_to_queued_then_is_lost_when_attempts_run_out(engine: Engine) -> None:
    job_id = queue.enqueue(engine, "t", max_attempts=2)
    first = queue.claim(engine, "w")
    assert first is not None and first.attempts == 1
    make_stale(engine, job_id)
    assert queue.requeue_stale(engine, STALE) == 1
    row = queue.get(engine, job_id)
    assert row is not None and row.state == "queued" and row.worker is None

    second = queue.claim(engine, "w")
    assert second is not None and second.attempts == 2
    make_stale(engine, job_id)
    queue.requeue_stale(engine, STALE)
    row = queue.get(engine, job_id)
    assert row is not None and row.state == "lost" and row.finished_at is not None


def test_fresh_heartbeat_protects_a_job_from_recovery(engine: Engine) -> None:
    queue.enqueue(engine, "t")
    job = queue.claim(engine, "w")
    assert job is not None
    assert queue.requeue_stale(engine, STALE) == 0


def test_stale_job_that_was_being_cancelled_becomes_cancelled(engine: Engine) -> None:
    queue.enqueue(engine, "t")
    job = queue.claim(engine, "w")
    assert job is not None
    queue.request_cancel(engine, job.id)
    make_stale(engine, job.id)
    queue.requeue_stale(engine, STALE)
    row = queue.get(engine, job.id)
    assert row is not None and row.state == "cancelled"


def test_late_result_from_a_presumed_dead_worker_is_ignored(engine: Engine) -> None:
    queue.enqueue(engine, "t")
    stale_attempt = queue.claim(engine, "slow")
    assert stale_attempt is not None
    make_stale(engine, stale_attempt.id)
    queue.requeue_stale(engine, STALE)
    retry = queue.claim(engine, "fast")
    assert retry is not None and retry.attempts == 2

    assert queue.complete(engine, stale_attempt, {"from": "slow"}) is False
    assert queue.heartbeat(engine, stale_attempt) is False
    assert queue.mark_running(engine, stale_attempt) is False
    row = queue.get(engine, retry.id)
    assert row is not None and row.state == "claimed" and row.worker == "fast" and row.result is None


def test_job_survives_a_killed_process(settings: Settings, engine: Engine) -> None:
    """A real process claims a job and dies without telling anyone; the next start recovers it."""
    queue.enqueue(engine, "t")
    code = (
        "import os, sys\n"
        "from pathlib import Path\n"
        "from edgebench import queue\n"
        "from edgebench.db import make_engine\n"
        "job = queue.claim(make_engine(Path(sys.argv[1])), 'doomed')\n"
        "os._exit(0 if job else 2)\n"
    )
    done = subprocess.run([sys.executable, "-c", code, str(settings.db_path)], check=False, timeout=60)
    assert done.returncode == 0
    assert queue.counts(engine)["claimed"] == 1
    claimed = queue.get(engine, 1)
    assert claimed is not None and claimed.id is not None
    make_stale(engine, claimed.id)
    assert queue.requeue_stale(engine, STALE) == 1
    job = queue.claim(engine, "restarted")
    assert job is not None and job.attempts == 2


def test_counts_cover_every_state(engine: Engine) -> None:
    queue.enqueue(engine, "t")
    counts = queue.counts(engine)
    assert counts["queued"] == 1 and set(counts) == {
        "queued",
        "claimed",
        "running",
        "done",
        "failed",
        "cancelled",
        "lost",
    }


def test_database_file_is_in_wal_mode(settings: Settings, engine: Engine) -> None:
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
    assert Path(settings.db_path).exists()
