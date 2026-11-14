"""The telemetry sampler: ``python -m edgebench_agent.telemetry --pid P --out FILE [--hz 5]``.

It runs as its own process, so reading the sensors never happens inside the benchmark, and writes one JSON line per
sample until the process it watches ends or it is stopped. Anything that cannot be read on this machine is ``null``,
never 0: the zero would read as a measurement. What each field means on each system is in ``describe()``, which the run
records as its environment.

Windows readings come from the performance counters (no administrator needed): ``% Processor Performance`` times the
nominal ``Processor Frequency`` is the clock, and ``Thermal Zone Information`` is the ACPI zone, which is the chassis or
board and not the CPU die. Linux and Raspberry Pi readings come from psutil, ``/sys`` and ``vcgencmd get_throttled``
(not tested on a Pi yet).
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import psutil

PDH_FMT_DOUBLE = 0x200
PDH_MORE_DATA = 0x800007D2
PROCESSOR_PERFORMANCE = r"\Processor Information(_Total)\% Processor Performance"
PROCESSOR_FREQUENCY = r"\Processor Information(_Total)\Processor Frequency"
THERMAL_ZONES = r"\Thermal Zone Information(*)\Temperature"


class _PdhValue(ctypes.Structure):
    _fields_ = (("CStatus", ctypes.c_ulong), ("doubleValue", ctypes.c_double))


class Pdh:
    """Windows performance counters through pdh.dll. ``read`` gives a value per counter path, None if unavailable."""

    def __init__(self, paths: list[str]) -> None:
        self.dll = ctypes.WinDLL("pdh.dll")  # type: ignore[attr-defined,unused-ignore]
        self.query = ctypes.c_void_p()
        if self.dll.PdhOpenQueryW(None, 0, ctypes.byref(self.query)) != 0:
            raise OSError("PdhOpenQuery failed")
        self.counters: dict[str, ctypes.c_void_p] = {}
        for path in self._expand(paths):
            handle = ctypes.c_void_p()
            if self.dll.PdhAddEnglishCounterW(self.query, path, 0, ctypes.byref(handle)) == 0:
                self.counters[path] = handle
        self.dll.PdhCollectQueryData(self.query)  # rate counters need two collections before they have a value

    def _expand(self, paths: list[str]) -> list[str]:
        out: list[str] = []
        for path in paths:
            if "*" not in path:
                out.append(path)
                continue
            size = ctypes.c_ulong(0)
            self.dll.PdhExpandWildCardPathW(None, path, None, ctypes.byref(size), 0)
            if size.value == 0:
                continue
            buffer = ctypes.create_unicode_buffer(size.value)
            if self.dll.PdhExpandWildCardPathW(None, path, buffer, ctypes.byref(size), 0) == 0:
                out.extend(p for p in buffer[: size.value].split("\x00") if p)
        return out

    def read(self) -> dict[str, float | None]:
        values: dict[str, float | None] = {path: None for path in self.counters}
        if self.dll.PdhCollectQueryData(self.query) != 0:
            return values
        for path, handle in self.counters.items():
            value = _PdhValue()
            got = self.dll.PdhGetFormattedCounterValue(handle, PDH_FMT_DOUBLE, None, ctypes.byref(value))
            if got == 0 and value.CStatus in (0, 1):  # PDH_CSTATUS_VALID_DATA, PDH_CSTATUS_NEW_DATA
                values[path] = float(value.doubleValue)
        return values

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.dll.PdhCloseQuery(self.query)


# `vcgencmd get_throttled`: bits 0-3 say what is happening now, bits 16-19 what happened at any time since boot.
THROTTLE_BITS = {0: "under-voltage", 1: "frequency capped", 2: "throttled", 3: "soft temperature limit"}


def decode_throttled(value: int) -> tuple[list[str], list[str]]:
    """(happening now, happened since boot). Only the first says anything about the run being measured."""
    return (
        [name for bit, name in THROTTLE_BITS.items() if value >> bit & 1],
        [name for bit, name in THROTTLE_BITS.items() if value >> (bit + 16) & 1],
    )


class Sources:
    """Everything this machine can tell us, read once per sample."""

    def __init__(self, pid: int | None) -> None:
        self.system = platform.system()
        self.pid = pid
        self.pdh: Pdh | None = None
        # EDGEBENCH_TELEMETRY_SKIP=clock,temperature,gpu leaves readings out, to find which sensor disturbs a benchmark
        skip = {s.strip() for s in os.environ.get("EDGEBENCH_TELEMETRY_SKIP", "").split(",")}
        paths = ([] if "clock" in skip else [PROCESSOR_PERFORMANCE, PROCESSOR_FREQUENCY]) + (
            [] if "temperature" in skip else [THERMAL_ZONES]
        )
        if self.system == "Windows" and paths:
            with contextlib.suppress(Exception):
                self.pdh = Pdh(paths)
        self.vcgencmd = shutil.which("vcgencmd") if self.system == "Linux" else None
        self._throttle_at, self._throttled = 0.0, None
        self.throttle_now: list[str] = []
        self.throttle_since_boot: list[str] = []
        self.gpu: Any = None
        with contextlib.suppress(Exception):
            if "gpu" in skip:
                raise ImportError("skipped")
            import pynvml  # type: ignore[import-not-found,unused-ignore]

            pynvml.nvmlInit()
            self.gpu = (pynvml, pynvml.nvmlDeviceGetHandleByIndex(0))
        psutil.cpu_percent(percpu=True)  # the first call has nothing to compare with

    def describe(self) -> dict[str, str | None]:
        """What each field is on this machine (None: not available here)."""
        windows = self.pdh is not None
        has_temp = bool(self.pdh and any("Thermal" in p for p in self.pdh.counters))
        return {
            "cpu": "psutil, per logical CPU",
            "ram": "resident memory of the benchmark process and its children",
            "clock": "% Processor Performance x nominal frequency (Windows performance counters)"
            if windows
            else ("psutil cpu_freq" if self.system != "Windows" else None),
            "temperature": "ACPI thermal zone, the chassis or board and not the CPU die (Windows performance counters)"
            if has_temp
            else ("psutil sensors / thermal zone" if self.system == "Linux" else None),
            "throttle": "vcgencmd get_throttled"
            if self.vcgencmd
            else None,  # Windows has no throttle flag without administrator rights; the clock drop stands in for it
            "gpu": "NVML" if self.gpu else None,
        }

    def _rss(self) -> float | None:
        if self.pid is None:
            return None
        try:
            parent = psutil.Process(self.pid)
            total = parent.memory_info().rss
            for child in parent.children(recursive=True):
                with contextlib.suppress(psutil.NoSuchProcess):
                    total += child.memory_info().rss
            return round(total / 1_048_576, 1)
        except psutil.NoSuchProcess:
            return None

    def _clock_and_temp(self) -> tuple[float | None, float | None]:
        if self.pdh is not None:
            v = self.pdh.read()
            perf, base = v.get(PROCESSOR_PERFORMANCE), v.get(PROCESSOR_FREQUENCY)
            clock = round(base * perf / 100.0, 1) if perf is not None and base else None
            zones = [x for p, x in v.items() if "Thermal" in p and x is not None and x > 0]
            return clock, (round(max(zones) - 273.15, 1) if zones else None)
        clock = None
        with contextlib.suppress(Exception):
            freq = psutil.cpu_freq()
            clock = round(freq.current, 1) if freq and freq.current else None
        temp = None
        with contextlib.suppress(Exception):
            sensors = psutil.sensors_temperatures() if hasattr(psutil, "sensors_temperatures") else {}
            readings = [t.current for entries in sensors.values() for t in entries if t.current]
            temp = round(max(readings), 1) if readings else None
        return clock, temp

    def _throttle(self) -> bool | None:
        if not self.vcgencmd:
            return None
        now = time.monotonic()
        if now - self._throttle_at >= 1.0:  # a subprocess per sample would cost more than the reading is worth
            self._throttle_at = now
            try:
                out = subprocess.run(
                    [self.vcgencmd, "get_throttled"], capture_output=True, text=True, timeout=2, check=False
                ).stdout
                self.throttle_now, self.throttle_since_boot = decode_throttled(int(out.strip().split("=")[1], 16))
                self._throttled = bool(self.throttle_now)
            except (OSError, subprocess.SubprocessError, ValueError, IndexError):
                self._throttled, self.throttle_now = None, []
        return self._throttled

    def _gpu(self) -> dict[str, float | None]:
        empty: dict[str, float | None] = {"gpu_util": None, "gpu_mem_mb": None, "gpu_temp_c": None}
        if not self.gpu:
            return empty
        nvml, handle = self.gpu
        try:
            return {
                "gpu_util": float(nvml.nvmlDeviceGetUtilizationRates(handle).gpu),
                "gpu_mem_mb": round(nvml.nvmlDeviceGetMemoryInfo(handle).used / 1_048_576, 1),
                "gpu_temp_c": float(nvml.nvmlDeviceGetTemperature(handle, nvml.NVML_TEMPERATURE_GPU)),
            }
        except Exception:
            return empty

    def sample(self) -> dict[str, Any]:
        cores = psutil.cpu_percent(percpu=True)
        clock, temp = self._clock_and_temp()
        return {
            "t": time.time(),
            "cpu": round(sum(cores) / len(cores), 1) if cores else None,
            "cores": [round(c, 1) for c in cores],
            "rss_mb": self._rss(),
            "clock_mhz": clock,
            "temp_c": temp,
            "throttled": self._throttle(),
            "throttle_now": self.throttle_now,
            **self._gpu(),
        }

    def close(self) -> None:
        if self.pdh:
            self.pdh.close()


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def summarise(samples: list[dict[str, Any]], t0: float, t1: float) -> dict[str, Any]:
    """The samples taken between two times, reduced to what a result shows. No readings for a field: None."""
    window = [s for s in samples if t0 <= s["t"] <= t1]

    def column(name: str) -> list[float]:
        return [float(s[name]) for s in window if s.get(name) is not None]

    cores = [s["cores"] for s in window if s.get("cores")]
    flags = [s["throttled"] for s in window if s.get("throttled") is not None]
    temps, clocks, rss = column("temp_c"), column("clock_mhz"), column("rss_mb")
    cpu = column("cpu")
    return {
        "samples": len(window),
        "cpu_mean": _mean(cpu),
        "cpu_max": max(cpu) if cpu else None,
        "cpu_per_core_mean": [round(sum(c) / len(cores), 1) for c in zip(*cores, strict=False)] if cores else None,
        "rss_peak_mb": max(rss) if rss else None,
        "clock_mhz_mean": _mean(clocks),
        "clock_mhz_min": min(clocks) if clocks else None,
        "temp_c_start": temps[0] if temps else None,
        "temp_c_max": max(temps) if temps else None,
        "throttled": any(flags) if flags else None,
        "throttle_reasons": sorted({r for s in window for r in s.get("throttle_now") or []}),
        "gpu_util_mean": _mean(column("gpu_util")),
        "gpu_mem_peak_mb": max(column("gpu_mem_mb")) if column("gpu_mem_mb") else None,
        "gpu_temp_c_max": max(column("gpu_temp_c")) if column("gpu_temp_c") else None,
    }


def read_file(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The sampler's header (what each field is here) and its samples. A line cut short by a kill is skipped."""
    header: dict[str, Any] = {}
    samples: list[dict[str, Any]] = []
    if not path.exists():
        return header, samples
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        with contextlib.suppress(ValueError):
            row = json.loads(line)
            if "t" in row:
                samples.append(row)
            else:
                header = row
    return header, samples


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--hz", type=float, default=5.0)
    args = ap.parse_args(argv)
    sources = Sources(args.pid)
    interval = 1.0 / args.hz
    try:
        with args.out.open("w", encoding="utf-8") as out:
            out.write(json.dumps({"describe": sources.describe(), "pid": os.getpid(), "hz": args.hz}) + "\n")
            out.flush()
            nxt = time.monotonic()
            while args.pid is None or psutil.pid_exists(args.pid):
                out.write(json.dumps(sources.sample()) + "\n")
                out.flush()
                nxt += interval
                time.sleep(max(0.0, nxt - time.monotonic()))
    finally:
        sources.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))


def environment() -> dict[str, Any]:
    """The things besides the model that decide how fast a run is: core layout and the power plan or governor."""
    env: dict[str, Any] = {
        "logical_cores": psutil.cpu_count(logical=True),
        "physical_cores": psutil.cpu_count(logical=False),
        "power_plan": None,
        "governor": None,
    }
    if platform.system() == "Windows":
        try:
            out = subprocess.run(
                ["powercfg", "/getactivescheme"], capture_output=True, text=True, timeout=5, check=False
            )
            text = out.stdout.strip()
            env["power_plan"] = text[text.index("(") + 1 : text.rindex(")")] if "(" in text else (text or None)
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    else:
        with contextlib.suppress(OSError):
            env["governor"] = Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor").read_text().strip()
    return env
