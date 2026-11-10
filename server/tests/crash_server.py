"""A real EdgeBench server process for tests/test_process_crash.py (not a test itself).

MODE=hang: the "sleepy" handler writes a marker file and then hangs, so the test can kill the process mid-job.
MODE=ok:   the handler finishes at once and reports which attempt it was.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import uvicorn

from edgebench import worker
from edgebench.config import Settings
from edgebench.main import create_app

MARKER = Path(os.environ["CRASH_MARKER"])
HANG = os.environ["CRASH_MODE"] == "hang"


@worker.register("sleepy")
def sleepy(ctx: worker.JobContext) -> dict[str, int]:
    if HANG:
        MARKER.write_text("started")
        time.sleep(120)
    return {"attempt": ctx.job.attempts}


settings = Settings(
    data_dir=Path(os.environ["CRASH_DATA"]),
    port=int(os.environ["CRASH_PORT"]),
    heartbeat_seconds=0.2,
    stale_seconds=1.5,
    worker_poll_seconds=0.1,
    _env_file=None,
)
uvicorn.run(create_app(settings), host="127.0.0.1", port=settings.port, log_config=None)
