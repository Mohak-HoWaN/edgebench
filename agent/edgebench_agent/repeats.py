"""Summaries of timed repeats (ADR 0004): per-repeat statistics, which repeats are valid, and the pooled figures.

Pure functions over plain dicts, so they are tested without a model or a sampler. A *repeat* is one run of N timed
iterations after its own warm-up; the benchmark child records each repeat's raw timings and its start and end time, and
the agent marks the
repeats that the telemetry shows were throttled before it pools the rest.
"""

from __future__ import annotations

from typing import Any

import numpy as np

CLOCK_DROP = 0.10  # a repeat whose clock averaged more than 10% below where the run started is not a clean measurement
STAGES = ("preprocess", "inference", "postprocess", "total")


def stats_ms(values_ms: list[float]) -> dict[str, float]:
    ms = np.asarray(values_ms, dtype=np.float64)
    return {
        "mean": float(ms.mean()),
        "std": float(ms.std()),
        "min": float(ms.min()),
        "p50": float(np.percentile(ms, 50)),
        "p95": float(np.percentile(ms, 95)),
        "p99": float(np.percentile(ms, 99)),
        "max": float(ms.max()),
    }


def pool(repeats: list[dict[str, Any]]) -> tuple[dict[str, dict[str, float]], list[float]]:
    """Pooled stage statistics and total timings of the given repeats (percentiles come from all iterations)."""
    stages = {name: stats_ms([x for r in repeats for x in r["samples_ms"][name]]) for name in STAGES}
    return stages, [x for r in repeats for x in r["samples_ms"]["total"]]


def finalize(speed: dict[str, Any], invalid: dict[int, str] | None = None, strip: bool = True) -> dict[str, Any]:
    """Mark each repeat valid or not and pool the valid ones into ``stages`` and ``total_ms``.

    ``strip`` drops the raw samples, which only the agent's second pass (after the telemetry is known) does.
    ``invalid`` maps a repeat's index to the reason. When no repeat is valid the pooled figures use all of them and
    ``latency_valid`` is False: the run is shown, but its latency is not to be compared.
    """
    repeats: list[dict[str, Any]] = speed["repeats"]
    invalid = invalid or {}
    for r in repeats:
        reason = invalid.get(int(r["index"]))
        r["valid"] = reason is None
        r["invalid_reason"] = reason
    valid = [r for r in repeats if r["valid"]]
    stages, total = pool(valid or repeats)
    speed["stages"], speed["total_ms"] = stages, [round(x, 3) for x in total]
    speed["valid_repeats"], speed["latency_valid"] = len(valid), bool(valid)
    for r in repeats:
        r["total_ms"] = [round(x, 3) for x in r["samples_ms"]["total"]]
        if strip:
            del r["samples_ms"]
    return speed


def invalid_repeats(windows: list[dict[str, Any]], start_clock_mhz: float | None) -> dict[int, str]:
    """Which repeats were throttled, from the telemetry summarised over each repeat's time window.

    A repeat is invalid when a throttle flag was up during it, or when its mean clock sat more than 10% below the
    clock the run started with. Without a clock reading (not available) only the flag can invalidate a repeat.
    """
    bad: dict[int, str] = {}
    for index, w in enumerate(windows):
        if w.get("throttled"):
            bad[index] = "the machine reported it was throttling during this repeat"
            continue
        clock = w.get("clock_mhz_mean")
        if start_clock_mhz and clock is not None and clock < start_clock_mhz * (1.0 - CLOCK_DROP):
            drop = round(100.0 * (1.0 - clock / start_clock_mhz))
            bad[index] = f"the CPU clock averaged {drop}% below where the run started"
    return bad


def merge_telemetry(
    result: dict[str, Any], header: dict[str, Any], samples: list[dict[str, Any]], environment: dict[str, Any]
) -> dict[str, Any]:
    """Attach each repeat's telemetry, mark the throttled repeats, pool the rest, and record the run's environment.

    With no samples (telemetry off, or the sampler could not start) every repeat is kept and the result says so.
    """
    from .telemetry import summarise

    result["environment"] = environment
    speed = result.get("speed")
    if not isinstance(speed, dict) or "repeats" not in speed:
        return result
    reps = speed["repeats"]
    if not samples:
        result["telemetry"] = {"enabled": False}
        finalize(speed)
        return result
    windows = [summarise(samples, r["t_start"], r["t_end"]) for r in reps]
    start_clock = summarise(samples, reps[0]["t_start"], reps[0]["t_start"] + 1.0)["clock_mhz_mean"]
    for r, w in zip(reps, windows, strict=True):
        r["telemetry"] = w
    finalize(speed, invalid_repeats(windows, start_clock))
    result["telemetry"] = {
        "enabled": True,
        "hz": header.get("hz"),
        "sources": header.get("describe"),
        "start_clock_mhz": start_clock,
        "run": summarise(samples, 0.0, float("inf")),
    }
    return result
