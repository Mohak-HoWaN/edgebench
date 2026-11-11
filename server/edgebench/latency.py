"""A run's latency as ADR 0004 reports it, and the comparison of two runs, computed from the repeats a run stored.

Computed when a run is read, not when it arrives, so runs from before repeats existed (one repeat, no interval)
show the same way.
"""

from __future__ import annotations

from typing import Any

from .stats import mean_interval, welch_test


def repeat_values(speed: dict[str, Any] | None) -> tuple[list[float], int, int]:
    """The per-repeat p50 values that count (milliseconds), how many repeats there were, and how many were valid.

    When no repeat is valid the values of all of them are returned so there is something to show; ``summary``
    marks that.
    """
    if not speed:
        return [], 0, 0
    repeats = speed.get("repeats")
    if repeats:
        valid = [r for r in repeats if r.get("valid", True)]
        return [float(r["stats"]["p50"]) for r in (valid or repeats)], len(repeats), len(valid)
    p50 = (speed.get("stages") or {}).get("total", {}).get("p50")
    return ([float(p50)], 1, 1) if p50 is not None else ([], 0, 0)


def summary(speed: dict[str, Any] | None) -> dict[str, Any] | None:
    """Headline latency: the mean of the repeats' p50 with a 95% Student t interval over the repeats."""
    values, total, valid = repeat_values(speed)
    if not values:
        return None
    iv = mean_interval(values)
    return {
        "p50_ms": iv.mean,
        "ci_half_width_ms": iv.half_width,
        "n": iv.n,
        "wide": iv.wide,
        "repeats": total,
        "valid_repeats": valid,
        "valid": valid > 0,  # False: every repeat was throttled, so this latency is not to be compared
        "fps": 1000.0 / iv.mean if iv.mean > 0 else None,
    }


def compare(
    reference: dict[str, Any] | None, other: dict[str, Any] | None, alpha: float = 0.05
) -> dict[str, Any] | None:
    """How ``other`` stands against ``reference``: the speed-up and Welch's test on the repeat values.

    ``significant`` is None when a test cannot be made (fewer than two valid repeats on a side, or a side that is
    not valid).
    """
    ref_values, _, ref_valid = repeat_values(reference)
    values, _, valid = repeat_values(other)
    if not ref_values or not values:
        return None
    ref_mean, mean = sum(ref_values) / len(ref_values), sum(values) / len(values)
    out: dict[str, Any] = {"speedup": ref_mean / mean if mean > 0 else None, "p": None, "t": None, "significant": None}
    if ref_valid == 0 or valid == 0:
        out["note"] = "a side of this comparison is not valid for latency (throttled)"
        return out
    test = welch_test(ref_values, values, alpha)
    if test is None:
        out["note"] = "needs at least 2 valid repeats on both sides to say whether the difference is real"
        return out
    out.update(p=test.p, t=test.t, significant=test.significant)
    return out
