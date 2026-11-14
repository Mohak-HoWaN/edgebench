"""Runs the converter scripts (``converter/``) in the converter environment, as separate processes.

The API process never imports torch or loads an uploaded model: every read and every conversion is a child process
that can be timed out, cancelled, and killed together with the helper programs it starts (ncnn's export runs
``pnnx``).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Settings

LOG_LIMIT = 64 * 1024
INFO_TTL = 120.0  # seconds a probe of the converter environment is trusted


@dataclass
class ConverterInfo:
    available: bool
    message: str | None = None
    python: str | None = None
    versions: dict[str, str] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    fingerprint: str = ""  # changes when a converter package or the converter script changes: part of the cache key


@dataclass
class Outcome:
    result: dict[str, Any] | None  # the script's RESULT line, None if it printed none
    exit_code: int | None
    reason: str  # "finished", "cancelled" or "timeout"
    log: str


def kill_tree(proc: subprocess.Popen[str]) -> None:
    """Stop a process and everything it started."""
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, check=False)
    else:
        with contextlib.suppress(ProcessLookupError):  # it exited between the check and the kill
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()


def _last_result(lines: list[str]) -> dict[str, Any] | None:
    for line in reversed(lines):
        if line.startswith("RESULT "):
            try:
                parsed = json.loads(line[len("RESULT ") :])
            except json.JSONDecodeError:
                return None
            return parsed if isinstance(parsed, dict) else None
    return None


class Converter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._info: ConverterInfo | None = None
        self._info_at: float | None = None  # None while the info was set from outside (tests)
        self._lock = threading.Lock()

    @property
    def convert_script(self) -> Path:
        return self.settings.converter_dir / "convert.py"

    @property
    def inspect_script(self) -> Path:
        return self.settings.converter_dir / "inspect_pt.py"

    def _run(
        self,
        args: list[str],
        timeout: float,
        cancelled: Callable[[], bool] | None = None,
        on_line: Callable[[str], None] | None = None,
    ) -> Outcome:
        python = self.settings.converter_python
        if python is None:
            raise RuntimeError("no converter Python is configured")
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        env.update({"YOLO_AUTOINSTALL": "False", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
        proc = subprocess.Popen(
            [str(python), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            start_new_session=sys.platform != "win32",
        )
        lines: list[str] = []
        kept = 0

        def pump() -> None:
            nonlocal kept
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.rstrip("\r\n")
                lines.append(line)
                kept += len(line) + 1
                while kept > LOG_LIMIT and len(lines) > 1:  # keep the tail: the end of a log is where the reason is
                    kept -= len(lines.pop(0)) + 1
                if on_line is not None:
                    # A failing callback (say, a locked database) must not stop this loop: if nothing drains the
                    # pipe the converter blocks on a full buffer and the real cause is hidden behind a timeout.
                    with contextlib.suppress(Exception):
                        on_line(line)

        reader = threading.Thread(target=pump, daemon=True)
        reader.start()
        deadline = time.monotonic() + timeout
        reason = "finished"
        while True:
            try:
                proc.wait(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                pass
            if cancelled is not None and cancelled():
                reason = "cancelled"
            elif time.monotonic() > deadline:
                reason = "timeout"
            if reason != "finished":
                kill_tree(proc)
                break
        reader.join(timeout=10)
        return Outcome(_last_result(lines), proc.returncode, reason, "\n".join(lines))

    def info(self, refresh: bool = False) -> ConverterInfo:
        """What the converter environment can do. Cached for INFO_TTL seconds, so an upgrade shows up without a restart;
        the probe imports nothing heavy."""
        with self._lock:
            fresh = self._info is not None and (self._info_at is None or time.monotonic() - self._info_at < INFO_TTL)
            if fresh and not refresh:
                assert self._info is not None
                return self._info
            self._info, self._info_at = self._probe(), time.monotonic()
            return self._info

    def _probe(self) -> ConverterInfo:
        python = self.settings.converter_python
        if python is None:
            return ConverterInfo(
                False, "No converter environment is set up. Set EDGEBENCH_CONVERTER_PYTHON (converter/README.md)."
            )
        if not Path(python).is_file():
            return ConverterInfo(False, f"The converter Python was not found at {python}.", python=str(python))
        if not self.convert_script.is_file():
            return ConverterInfo(
                False, f"The converter scripts were not found in {self.settings.converter_dir}.", python=str(python)
            )
        out = self._run([str(self.convert_script), "--probe"], timeout=60)
        r = out.result
        if r is None or not r.get("ok"):
            return ConverterInfo(
                False,
                "The converter Python did not start: " + (out.log.strip().splitlines() or ["no output"])[-1],
                str(python),
            )
        versions: dict[str, str] = r.get("versions", {})
        missing: list[str] = r.get("missing", [])
        digest = hashlib.sha256(
            json.dumps(versions, sort_keys=True).encode() + self.convert_script.read_bytes()
        ).hexdigest()[:16]
        # A missing package only blocks the formats that need it, so the environment still counts as available.
        needed = [p for p in ("torch", "ultralytics") if p in missing]
        if needed:
            return ConverterInfo(
                False, f"The converter environment lacks {', '.join(needed)}.", str(python), versions, missing, digest
            )
        return ConverterInfo(True, None, str(python), versions, missing, digest)

    def run_inspect(self, pt: Path, timeout: float = 180) -> Outcome:
        return self._run([str(self.inspect_script), str(pt)], timeout=timeout)

    def run_convert(
        self,
        *,
        op: str,
        pt: Path,
        out: Path,
        imgsz: int,
        source: Path | None,
        simplify: bool,
        cancelled: Callable[[], bool],
        on_line: Callable[[str], None],
        calibration: Path | None = None,
    ) -> Outcome:
        args = [str(self.convert_script), "--op", op, "--pt", str(pt), "--out", str(out), "--imgsz", str(imgsz)]
        if source is not None:
            args += ["--source", str(source)]
        if not simplify:
            args.append("--no-simplify")
        if calibration is not None:
            args += ["--calibration", str(calibration)]
        return self._run(args, self.settings.converter_timeout_seconds, cancelled, on_line)
