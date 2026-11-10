"""The agent: enrol once, then claim jobs, fetch what they need, run each in its own process and report back."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import psutil

from . import __version__
from .cache import Cache
from .client import Cancelled, Rejected, ServerClient
from .fingerprint import collect

log = logging.getLogger("edgebench_agent")
HEARTBEAT_SECONDS = 5.0
LOG_LINES = 60
PACKAGE_PARENT = Path(__file__).resolve().parents[1]  # where `-m edgebench_agent.bench` is importable from


def kill_tree(pid: int) -> None:
    """Stop a process and everything it started (a benchmark may spawn helpers)."""
    try:
        parent = psutil.Process(pid)
        for child in parent.children(recursive=True):
            child.kill()
        parent.kill()
    except psutil.NoSuchProcess:
        pass


class Agent:
    def __init__(
        self,
        client: ServerClient,
        state_dir: Path,
        python: str = sys.executable,
        heartbeat_seconds: float = HEARTBEAT_SECONDS,
        bench_module: str = "edgebench_agent.bench",
    ) -> None:
        self.client, self.state_dir, self.python = client, state_dir, python
        self.heartbeat_seconds, self.bench_module = heartbeat_seconds, bench_module
        self.cache = Cache(state_dir / "cache")
        self._progress: tuple[float | None, str | None] = (None, None)
        self._stop_run = threading.Event()  # the server said cancel (or the job is no longer ours)
        self._stopped = threading.Event()

    # --- enrolment -------------------------------------------------------------------------------------------------

    def enroll(self, token: str, name: str | None = None) -> dict[str, Any]:
        data = self.client.enroll(token, collect(), __version__, name)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "agent.json").write_text(
            json.dumps({"device_id": data["device_id"], "device_token": data["device_token"], "kind": data["kind"]}),
            encoding="utf-8",
        )
        return data

    def load_identity(self) -> bool:
        path = self.state_dir / "agent.json"
        if not path.exists():
            return False
        self.client.token = json.loads(path.read_text(encoding="utf-8"))["device_token"]
        return True

    # --- one job ---------------------------------------------------------------------------------------------------

    def _beat_loop(self, job_id: int, done: threading.Event) -> None:
        while not done.wait(self.heartbeat_seconds):
            try:
                answer = self.client.heartbeat(job_id, *self._progress, __version__)
            except (httpx.HTTPError, Rejected):
                continue  # a lost heartbeat is not fatal: the server waits 30 s before it gives up on us
            if answer.get("cancel"):
                self._stop_run.set()

    def run_job(self, job: dict[str, Any]) -> None:
        job_id = int(job["job_id"])
        self._stop_run.clear()
        self._progress = (0.0, "Starting")
        done = threading.Event()
        beat = threading.Thread(target=self._beat_loop, args=(job_id, done), daemon=True)
        beat.start()
        try:
            self._execute(job_id, job)
        except Cancelled:
            self._report(job_id, ok=False, kind="cancelled")
        except Rejected:
            raise
        except Exception as exc:
            log.exception("run failed before it started")
            self._report(job_id, ok=False, kind="failed", error=f"{type(exc).__name__}: {exc}")
        finally:
            done.set()
            beat.join()

    def _report(self, job_id: int, **outcome: Any) -> None:
        """Send the result. If the server cannot be reached the run is marked lost on its side (it notices the silence);
        the agent stays up and takes the next job once the server is back."""
        try:
            self.client.result(job_id, **outcome)
        except httpx.HTTPError as exc:
            log.warning(
                "could not report the result of job %s (%s); the server will mark it lost", job_id, type(exc).__name__
            )

    def _execute(self, job_id: int, job: dict[str, Any]) -> None:
        stop = self._stop_run.is_set
        self._progress = (0.0, "Fetching the model")
        model_path = self.cache.model(self.client, job["artifact"], stop)
        self._progress = (0.0, "Fetching the dataset")
        dataset_dir = self.cache.dataset(self.client, job["dataset"], stop)
        if stop():
            raise Cancelled
        params = job["params"]
        spec = {
            "kind": job["kind"],
            "model_path": str(model_path),
            "imgsz": job["imgsz"],
            "dataset_dir": str(dataset_dir),
            "model_names": job["model_names"],
            "dataset_names_generic": job["dataset"]["names_generic"],
            **{k: params[k] for k in ("threads", "conf", "iou", "max_det", "warmup", "iterations", "accuracy")},
            "max_images": params.get("max_images"),
            "cpu_list": params.get("cpu_list"),
        }
        work = self.state_dir / "jobs" / str(job_id)
        work.mkdir(parents=True, exist_ok=True)
        spec_path = work / "spec.json"
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        outcome = self._run_child(spec_path)
        if outcome is None:
            raise Cancelled
        self._report(job_id, **outcome)

    def _run_child(self, spec_path: Path) -> dict[str, Any] | None:
        env = {**os.environ, "YOLO_AUTOINSTALL": "False", "PYTHONUNBUFFERED": "1"}
        proc = subprocess.Popen(
            [self.python, "-m", self.bench_module, str(spec_path)],
            cwd=PACKAGE_PARENT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
        )
        lines: list[str] = []
        final: dict[str, Any] | None = None

        def read() -> None:
            nonlocal final
            assert proc.stdout is not None
            for raw in proc.stdout:
                text = raw.rstrip()
                if text.startswith("PROGRESS "):
                    self._progress = (float(text.split()[1]), "Running")
                elif text.startswith("RESULT "):
                    final = json.loads(text[7:])
                else:
                    lines.append(text)
                    del lines[:-LOG_LINES]

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        while proc.poll() is None:
            if self._stop_run.is_set():
                kill_tree(proc.pid)
                proc.wait()
                reader.join(timeout=5)
                return None
            time.sleep(0.1)
        reader.join(timeout=10)
        log_text = "\n".join(lines)[-6000:]
        if final is None:
            code = proc.returncode
            return {
                "ok": False,
                "kind": "failed",
                "error": f"The benchmark process stopped unexpectedly (exit code {code}). The agent is still running.",
                "log": log_text,
            }
        ok = bool(final.pop("ok", False))
        kind, error = str(final.pop("kind", "failed")), final.pop("error", None)
        return {"ok": ok, "kind": kind, "error": error, "result": final if ok else None, "log": log_text or None}

    # --- the loop --------------------------------------------------------------------------------------------------

    def serve(self, once: bool = False) -> None:
        """Claim and run jobs until stopped. ``once`` returns after the first job (for tests and trials)."""
        while not self._stopped.is_set():
            try:
                job = self.client.claim()
            except httpx.HTTPError as exc:
                log.warning("cannot reach the server (%s); retrying", type(exc).__name__)
                self._stopped.wait(5)
                continue
            if job is None:
                with contextlib.suppress(httpx.HTTPError):  # idle heartbeat: keeps the device online between jobs
                    self.client.heartbeat(None, None, None, __version__)
                continue
            self.run_job(job)
            if once:
                return

    def stop(self) -> None:
        self._stopped.set()
