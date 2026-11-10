"""Runs queued jobs. A handler does the work (later phases run converters and benchmarks in subprocesses from here);
the worker only claims, heartbeats, honours cancellation and records the outcome."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Engine

from . import queue
from .queue import Claimed

log = logging.getLogger(__name__)
Publish = Callable[[dict[str, Any]], None]


class Cancelled(Exception):
    """Raised inside a handler when the job was cancelled."""


class PermanentError(Exception):
    """Raised by a handler for a failure that a retry cannot fix; the job fails at once."""


class OwnershipLost(Exception):
    """Raised inside a handler when the job was recovered as stale and given to another worker."""


@dataclass
class JobContext:
    job: Claimed
    engine: Engine
    publish: Publish
    lost: threading.Event = field(default_factory=threading.Event)

    @property
    def params(self) -> dict[str, Any]:
        return self.job.params

    def check_cancelled(self) -> None:
        """Stop the handler if the job was cancelled or is no longer ours. Handlers call this between steps."""
        if self.lost.is_set():
            raise OwnershipLost
        if queue.cancel_requested(self.engine, self.job):
            raise Cancelled

    def progress(self, fraction: float, message: str = "") -> None:
        """Report progress (0..1) and stop here if the job was cancelled."""
        self.publish({"type": "job.progress", "id": self.job.id, "fraction": fraction, "message": message})
        self.check_cancelled()


Handler = Callable[[JobContext], dict[str, Any] | None]
_HANDLERS: dict[str, Handler] = {}


def register(job_type: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        _HANDLERS[job_type] = fn
        return fn

    return deco


def unregister(job_type: str) -> None:
    _HANDLERS.pop(job_type, None)


class Worker:
    def __init__(
        self,
        engine: Engine,
        publish: Publish,
        *,
        name: str = "worker-1",
        poll_seconds: float = 0.5,
        heartbeat_seconds: float = 5.0,
        stale_seconds: float = 30.0,
    ) -> None:
        self.engine, self.publish, self.name = engine, publish, name
        self.poll_seconds, self.heartbeat_seconds, self.stale_seconds = poll_seconds, heartbeat_seconds, stale_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name=self.name, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    def _loop(self) -> None:
        next_sweep = 0.0
        while not self._stop.is_set():
            try:
                now = time.monotonic()
                if now >= next_sweep:
                    recovered = queue.requeue_stale(self.engine, self.stale_seconds)
                    next_sweep = now + max(1.0, self.stale_seconds / 3)
                    if recovered:
                        log.warning("recovered stale jobs", extra={"count": recovered})
                        self.publish({"type": "queue.recovered", "count": recovered})
                if not self.run_once():
                    self._stop.wait(self.poll_seconds)
            except Exception:
                log.exception("worker loop error")
                self._stop.wait(self.poll_seconds)

    def run_once(self) -> bool:
        """Claim and run one job. Returns False when the queue was empty."""
        job = queue.claim(self.engine, self.name)
        if job is None:
            return False
        self._emit(job, "claimed")
        if not queue.mark_running(self.engine, job):
            # Recovered as stale between claim and start (a long pause): another worker owns it. Do not run it twice.
            log.warning("job was taken over before it started", extra={"job_id": job.id})
            return True
        self._emit(job, "running")
        ctx = JobContext(job, self.engine, self.publish)
        done = threading.Event()
        beat = threading.Thread(target=self._beat, args=(job, done, ctx.lost), daemon=True)
        beat.start()
        try:
            handler = _HANDLERS.get(job.type)
            if handler is None:
                raise PermanentError(f"no handler registered for job type {job.type!r}")
            result = handler(ctx)
            if queue.complete(self.engine, job, result):
                self._emit(job, "done")
            else:
                log.warning("finished a job that was taken over; result discarded", extra={"job_id": job.id})
        except OwnershipLost:
            log.warning("stopped a job that was taken over", extra={"job_id": job.id})
        except Cancelled:
            queue.mark_cancelled(self.engine, job)
            self._emit(job, "cancelled")
        except PermanentError as exc:
            self._emit(job, queue.fail(self.engine, job, str(exc), retry=False) or "failed", error=str(exc))
        except Exception as exc:
            log.exception("job failed", extra={"job_id": job.id, "job_type": job.type})
            state = queue.fail(self.engine, job, f"{type(exc).__name__}: {exc}")
            self._emit(job, state or "failed", error=str(exc))
        finally:
            done.set()
            beat.join()
        return True

    def _beat(self, job: Claimed, done: threading.Event, lost: threading.Event) -> None:
        """Keep the job's heartbeat fresh. A failed write is logged and retried; losing the job stops the handler."""
        while not done.wait(self.heartbeat_seconds):
            try:
                if not queue.heartbeat(self.engine, job):
                    lost.set()
                    return
            except Exception:
                log.exception("heartbeat write failed", extra={"job_id": job.id})

    def _emit(self, job: Claimed, state: str, **extra: Any) -> None:
        self.publish(
            {"type": "job.state", "id": job.id, "job_type": job.type, "state": state, "attempt": job.attempts, **extra}
        )
