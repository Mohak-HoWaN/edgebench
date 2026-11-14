from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import psutil
import pytest

from edgebench_agent import telemetry
from edgebench_agent.telemetry import decode_throttled, environment, read_file, summarise

PACKAGE_PARENT = Path(__file__).resolve().parents[1]


def row(t: float, **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "t": t,
        "cpu": 10.0,
        "cores": [10.0, 30.0],
        "rss_mb": 100.0,
        "clock_mhz": 3000.0,
        "temp_c": 60.0,
        "throttled": None,
        "gpu_util": None,
        "gpu_mem_mb": None,
        "gpu_temp_c": None,
    }
    return {**base, **kw}


def test_a_window_is_summarised_from_its_own_samples_only() -> None:
    samples = [
        row(1.0, cpu=100.0),
        row(2.0, cpu=20.0, rss_mb=150.0),
        row(3.0, cpu=40.0, rss_mb=120.0),
        row(9.0, cpu=0.0),
    ]
    w = summarise(samples, 2.0, 3.0)
    assert w["samples"] == 2 and w["cpu_mean"] == 30.0 and w["cpu_max"] == 40.0 and w["rss_peak_mb"] == 150.0
    assert w["cpu_per_core_mean"] == [10.0, 30.0]


def test_a_reading_that_is_not_available_stays_none_and_is_never_zero() -> None:
    w = summarise([row(1.0, clock_mhz=None, temp_c=None), row(2.0, clock_mhz=None, temp_c=None)], 0.0, 5.0)
    assert w["clock_mhz_mean"] is None and w["clock_mhz_min"] is None and w["temp_c_max"] is None
    assert w["throttled"] is None and w["gpu_util_mean"] is None and w["gpu_mem_peak_mb"] is None
    empty = summarise([], 0.0, 1.0)
    assert empty["samples"] == 0 and empty["cpu_mean"] is None and empty["cpu_per_core_mean"] is None


def test_a_throttle_flag_in_any_sample_shows_in_the_window() -> None:
    assert summarise([row(1.0, throttled=False), row(2.0, throttled=True)], 0.0, 3.0)["throttled"] is True
    assert summarise([row(1.0, throttled=False)], 0.0, 3.0)["throttled"] is False


def test_the_file_reader_skips_a_line_cut_short_by_killing_the_sampler(tmp_path: Path) -> None:
    path = tmp_path / "t.ndjson"
    path.write_text('{"describe": {"cpu": "x"}, "hz": 5.0}\n{"t": 1.0, "cpu": 5.0}\n{"t": 2.0, "cp', encoding="utf-8")
    header, samples = read_file(path)
    assert header["hz"] == 5.0 and [s["t"] for s in samples] == [1.0]
    assert read_file(tmp_path / "missing.ndjson") == ({}, [])


def start_sampler(out: Path, pid: int) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-m", "edgebench_agent.telemetry", "--pid", str(pid), "--out", str(out), "--hz", "10"],
        cwd=PACKAGE_PARENT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_the_sampler_is_a_separate_process_that_watches_the_target_and_stops_when_it_ends(tmp_path: Path) -> None:
    target = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    out = tmp_path / "t.ndjson"
    sampler = start_sampler(out, target.pid)
    try:
        assert sampler.pid not in (target.pid, os.getpid())  # its own process, not the benchmark and not the agent
        deadline = time.monotonic() + 15  # starting Python and the counters takes a moment, longer when busy
        header, samples = read_file(out)
        while len(samples) < 5 and time.monotonic() < deadline:
            time.sleep(0.2)
            header, samples = read_file(out)
        # a venv launcher on Windows starts the real interpreter as a child, so the sampler is the launcher or its child
        own = {sampler.pid, *(c.pid for c in psutil.Process(sampler.pid).children(recursive=True))}
        assert header["pid"] in own and header["pid"] not in (target.pid, os.getpid()) and header["hz"] == 10.0
        assert len(samples) >= 5 and all(s["cores"] for s in samples)
        assert any(s["rss_mb"] for s in samples)  # it measures the watched process, not itself
        target.kill()
        target.wait(timeout=10)
        assert sampler.wait(timeout=10) == 0  # the target ended, so the sampler did too
    finally:
        for proc in (target, sampler):
            if proc.poll() is None:
                proc.kill()


def test_the_environment_names_the_core_layout_and_the_power_plan_or_governor() -> None:
    env = environment()
    assert env["logical_cores"] and env["physical_cores"] and set(env) >= {"power_plan", "governor"}
    assert env["power_plan"] or env["governor"]  # one of the two is known on any system this runs on


def test_throttle_bits_are_decoded_and_only_the_current_ones_flag_a_run() -> None:
    assert decode_throttled(0) == ([], [])
    assert decode_throttled(0x50005) == (["under-voltage", "throttled"], ["under-voltage", "throttled"])
    assert decode_throttled(0x50000) == ([], ["under-voltage", "throttled"])  # long past: says nothing about this run
    assert decode_throttled(0x8) == (["soft temperature limit"], [])


def test_a_pi_profile_reads_the_throttle_flag_from_a_stand_in_vcgencmd(monkeypatch: pytest.MonkeyPatch) -> None:
    """The agent on this PC with `vcgencmd` replaced by a fixture: the same code path a Pi takes."""
    answers = iter(["throttled=0x0", "throttled=0x50005", "throttled=0x50000", "garbage"])
    monkeypatch.setattr(telemetry.platform, "system", lambda: "Linux")
    monkeypatch.setattr(telemetry.shutil, "which", lambda name: "/usr/bin/vcgencmd" if name == "vcgencmd" else None)
    monkeypatch.setattr(
        telemetry.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=next(answers) + "\n"),
    )
    src = telemetry.Sources(None)
    assert src.describe()["throttle"] == "vcgencmd get_throttled"
    seen = []
    for _ in range(4):
        src._throttle_at = 0.0  # let the one-second cache expire
        seen.append((src._throttle(), list(src.throttle_now)))
    assert seen == [(False, []), (True, ["under-voltage", "throttled"]), (False, []), (None, [])]
    # and the repeat is marked: a window with a current flag lists why
    w = summarise([row(1.0, throttled=True, throttle_now=["under-voltage"]), row(2.0, throttled=False)], 0.0, 3.0)
    assert w["throttled"] is True and w["throttle_reasons"] == ["under-voltage"]
