"""Phase 0 spike 3: what telemetry does this Windows laptop actually expose, and what does sampling cost?

Run from spikes/ (nothing else heavy running):  .venv\\Scripts\\python scripts\\s3_telemetry.py
Writes out/s3_results.json.
"""

from __future__ import annotations

import ctypes
import json
import multiprocessing as mp
import subprocess
import time
from pathlib import Path

import psutil

SP = Path(__file__).resolve().parent.parent
res: dict = {}


def guarded(name: str, fn) -> None:
    try:
        res[name] = fn()
    except BaseException as exc:  # noqa: BLE001
        res[name] = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}


def cpu_sensors() -> dict:
    temps = getattr(psutil, "sensors_temperatures", None)
    return {"psutil_sensors_temperatures_exists": temps is not None, "value": temps() if temps else None}


def wmi_thermal() -> dict:
    cmd = ("Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction Stop | "
           "Select-Object -ExpandProperty CurrentTemperature")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=30)
    vals = [int(x) / 10 - 273.15 for x in out.stdout.split() if x.strip().isdigit()]
    return {"celsius": vals, "stderr": out.stderr.strip()[:200]}


def cpu_freq_under_load() -> dict:
    import sys

    idle = psutil.cpu_freq()
    procs = [subprocess.Popen([sys.executable, "-c", "while True: pass"]) for _ in range(psutil.cpu_count(logical=False))]
    try:
        time.sleep(4)
        samples = []
        for _ in range(5):
            samples.append(psutil.cpu_freq().current)
            time.sleep(0.4)
        percpu = psutil.cpu_percent(percpu=True, interval=1.0)
    finally:
        for p in procs:
            p.kill()
    return {"idle_mhz": idle.current, "max_mhz_reported": idle.max, "under_load_mhz": samples,
            "per_core_percent_under_load": percpu, "logical": psutil.cpu_count(), "physical": psutil.cpu_count(logical=False)}


def gpu() -> dict:
    import pynvml

    pynvml.nvmlInit()
    h = pynvml.nvmlDeviceGetHandleByIndex(0)
    util = pynvml.nvmlDeviceGetUtilizationRates(h)
    mem = pynvml.nvmlDeviceGetMemoryInfo(h)
    out = {
        "name": pynvml.nvmlDeviceGetName(h),
        "temp_c": pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU),
        "util_gpu_pct": util.gpu, "util_mem_pct": util.memory,
        "mem_used_mb": mem.used // 2**20, "mem_total_mb": mem.total // 2**20,
        "clock_sm_mhz": pynvml.nvmlDeviceGetClockInfo(h, pynvml.NVML_CLOCK_SM),
        "clock_sm_max_mhz": pynvml.nvmlDeviceGetMaxClockInfo(h, pynvml.NVML_CLOCK_SM),
    }
    try:
        reasons = pynvml.nvmlDeviceGetCurrentClocksThrottleReasons(h)
        out["throttle_reason_bitmask"] = int(reasons)
    except pynvml.NVMLError as exc:
        out["throttle_reason_error"] = str(exc)
    return out


def power_plan() -> dict:
    out = subprocess.run(["powercfg", "/getactivescheme"], capture_output=True, text=True, timeout=15)
    return {"active_scheme": out.stdout.strip()}


def timers() -> dict:
    import ctypes.wintypes as wt  # noqa: F401

    mn, mx, cur = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_ulong()
    ctypes.windll.ntdll.NtQueryTimerResolution(ctypes.byref(mn), ctypes.byref(mx), ctypes.byref(cur))
    info = time.get_clock_info("perf_counter")
    return {"timer_resolution_ms_current": cur.value / 1e4, "timer_resolution_ms_best": mx.value / 1e4,
            "perf_counter_resolution_ns": info.resolution, "perf_counter_monotonic": info.monotonic}


def sampler(seconds: float, hz: float, q) -> None:
    """Runs in a separate process: samples at `hz`, reports the process's own CPU time and sample jitter."""
    p = psutil.Process()
    t0, n, period = time.perf_counter(), 0, 1 / hz
    stamps = []
    while time.perf_counter() - t0 < seconds:
        psutil.cpu_percent(percpu=True)
        psutil.virtual_memory()
        stamps.append(time.perf_counter())
        n += 1
        time.sleep(max(0.0, t0 + n * period - time.perf_counter()))
    cpu = p.cpu_times()
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    q.put({"samples": n, "own_cpu_seconds": round(cpu.user + cpu.system, 3),
           "gap_ms_mean": round(sum(gaps) / len(gaps) * 1000, 1), "gap_ms_max": round(max(gaps) * 1000, 1)})


def sampler_process_cost() -> dict:
    q = mp.Queue()
    proc = mp.Process(target=sampler, args=(10.0, 5.0, q))
    proc.start()
    out = q.get(timeout=30)
    proc.join()
    out["separate_pid"] = proc.pid != mp.current_process().pid
    out["cpu_pct_of_one_core"] = round(out["own_cpu_seconds"] / 10.0 * 100, 2)
    return out


if __name__ == "__main__":
    guarded("cpu_temperature_psutil", cpu_sensors)
    guarded("cpu_temperature_wmi_acpi", wmi_thermal)
    guarded("cpu_clock_and_per_core", cpu_freq_under_load)
    guarded("gpu_nvml", gpu)
    guarded("power_plan", power_plan)
    guarded("timers", timers)
    guarded("sampler_5hz_separate_process", sampler_process_cost)
    (SP / "out" / "s3_results.json").write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps(res, indent=2, default=str))
