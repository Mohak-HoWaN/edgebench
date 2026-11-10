from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable
from functools import partial
from pathlib import Path

from sqlalchemy import Engine

from edgebench import queue
from edgebench.db import make_engine, migrate

SERVER = Path(__file__).with_name("crash_server.py")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def wait_until(check: Callable[[], bool], timeout: float, what: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {what}")


def start_server(tmp_path: Path, port: int, mode: str) -> subprocess.Popen[bytes]:
    env = {
        **os.environ,
        "CRASH_DATA": str(tmp_path / "data"),
        "CRASH_PORT": str(port),
        "CRASH_MARKER": str(tmp_path / "started.txt"),
        "CRASH_MODE": mode,
    }
    return subprocess.Popen([sys.executable, str(SERVER)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
            return bool(r.status == 200)
    except OSError:
        return False


def test_a_server_killed_mid_job_is_replaced_by_one_that_finishes_the_job(tmp_path: Path) -> None:
    """The end-to-end version of the crash promise: real server process, hard kill, fresh process, same database."""
    db = tmp_path / "data" / "edgebench.db"
    migrate(db)
    engine: Engine = make_engine(db)
    job_id = queue.enqueue(engine, "sleepy")
    port = free_port()

    first = start_server(tmp_path, port, "hang")
    second: subprocess.Popen[bytes] | None = None
    try:
        wait_until(partial(healthy, port), 30, "the first server to answer")
        wait_until((tmp_path / "started.txt").exists, 30, "the handler to start")
        row = queue.get(engine, job_id)
        assert row is not None and row.state == "running" and row.attempts == 1

        first.kill()  # TerminateProcess / SIGKILL: no shutdown code runs, the job is left "running"
        first.wait(timeout=15)
        row = queue.get(engine, job_id)
        assert row is not None and row.state == "running"

        second = start_server(tmp_path, port, "ok")
        wait_until(partial(healthy, port), 30, "the second server to answer")

        def finished() -> bool:
            r = queue.get(engine, job_id)
            return r is not None and r.state == "done"

        wait_until(finished, 30, "the second server to finish the job")
        row = queue.get(engine, job_id)
        assert row is not None and row.result == {"attempt": 2} and row.attempts == 2
        assert queue.counts(engine)["done"] == 1
    finally:
        for proc in (first, second):
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.wait(timeout=15)
        if first.stderr is not None:
            first.stderr.close()
        if second is not None and second.stderr is not None:
            second.stderr.close()
        engine.dispose()
