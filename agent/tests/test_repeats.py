from __future__ import annotations

from typing import Any

import pytest

from edgebench_agent.repeats import finalize, invalid_repeats, merge_telemetry, series


def repeat(index: int, level: float, t0: float) -> dict[str, Any]:
    """A repeat whose every iteration took ``level`` ms in total (1, 2 and level-3 for the three stages)."""
    n = 10
    return {
        "index": index,
        "t_start": t0,
        "t_end": t0 + 10,
        "stats": {},
        "samples_ms": {
            "preprocess": [1.0] * n,
            "inference": [2.0] * n,
            "postprocess": [level - 3.0] * n,
            "total": [level] * n,
        },
    }


def speed_of(*levels: float) -> dict[str, Any]:
    return {"repeats": [repeat(i, level, 100.0 * i) for i, level in enumerate(levels)]}


def test_a_throttled_repeat_is_flagged_and_left_out_of_the_pooled_figures() -> None:
    speed = finalize(speed_of(10.0, 10.0, 40.0), {2: "the machine reported it was throttling during this repeat"})
    assert [r["valid"] for r in speed["repeats"]] == [True, True, False]
    assert speed["stages"]["total"]["p50"] == 10.0 and speed["stages"]["total"]["max"] == 10.0
    assert speed["valid_repeats"] == 2 and speed["latency_valid"] and len(speed["total_ms"]) == 20
    assert "throttling" in speed["repeats"][2]["invalid_reason"]
    assert all(
        "samples_ms" not in r and len(r["total_ms"]) == 10 for r in speed["repeats"]
    )  # the figures stay recomputable


def test_when_every_repeat_is_throttled_the_run_is_shown_but_not_valid_for_latency() -> None:
    speed = finalize(speed_of(10.0, 30.0), {0: "slow", 1: "slow"})
    assert speed["valid_repeats"] == 0 and speed["latency_valid"] is False
    assert speed["stages"]["total"]["mean"] == 20.0  # all repeats pooled, so there is something to show


def test_the_child_can_leave_the_raw_samples_for_the_agents_second_pass() -> None:
    speed = finalize(speed_of(10.0), strip=False)
    assert "samples_ms" in speed["repeats"][0] and speed["latency_valid"]
    finalize(speed, {0: "x"})  # the second pass pools again with the verdict
    assert speed["latency_valid"] is False and "samples_ms" not in speed["repeats"][0]


def test_the_clock_dropping_more_than_ten_percent_invalidates_a_repeat() -> None:
    windows = [{"clock_mhz_mean": 3000.0}, {"clock_mhz_mean": 2750.0}, {"clock_mhz_mean": 2600.0}]
    bad = invalid_repeats(windows, 3000.0)
    assert set(bad) == {2} and "13%" in bad[2]  # 8% lower is within the noise, 13% lower is not


def test_a_throttle_flag_invalidates_a_repeat_whatever_the_clock_says() -> None:
    assert set(invalid_repeats([{"throttled": True, "clock_mhz_mean": 3000.0}, {"throttled": False}], 3000.0)) == {0}


def test_without_a_clock_reading_only_the_flag_can_invalidate() -> None:
    assert invalid_repeats([{"clock_mhz_mean": None}, {"throttled": None}], None) == {}
    assert invalid_repeats([{"clock_mhz_mean": 1.0}], None) == {}  # no starting clock to compare with


def sample(t: float, clock: float | None, throttled: bool | None = None) -> dict[str, Any]:
    return {
        "t": t,
        "cpu": 50.0,
        "cores": [50.0, 50.0],
        "rss_mb": 120.0,
        "clock_mhz": clock,
        "temp_c": 60.0,
        "throttled": throttled,
    }


def test_merge_attaches_each_repeats_window_and_flags_the_one_that_ran_slow() -> None:
    result: dict[str, Any] = {"speed": speed_of(10.0, 10.0, 25.0)}
    samples = [sample(t, 3000.0) for t in range(0, 200)] + [sample(t, 2400.0) for t in range(200, 300)]
    out = merge_telemetry(result, {"hz": 5.0, "describe": {"clock": "x"}}, samples, {"power_plan": "Balanced"})
    reps = out["speed"]["repeats"]
    assert [r["valid"] for r in reps] == [True, True, False] and "20%" in reps[2]["invalid_reason"]
    assert reps[0]["telemetry"]["rss_peak_mb"] == 120.0 and out["telemetry"]["start_clock_mhz"] == 3000.0
    assert out["telemetry"]["enabled"] and out["environment"]["power_plan"] == "Balanced"
    assert out["speed"]["stages"]["total"]["p50"] == 10.0


def test_merge_without_samples_keeps_every_repeat_and_says_telemetry_was_off() -> None:
    out = merge_telemetry({"speed": speed_of(10.0, 12.0)}, {}, [], {})
    assert out["telemetry"] == {"enabled": False} and out["speed"]["valid_repeats"] == 2


def test_merge_leaves_a_result_without_repeats_alone() -> None:
    out = merge_telemetry({"speed": {"stages": {"total": {"p50": 9.5}}}}, {}, [sample(0, 1.0)], {"x": 1})
    assert out["speed"] == {"stages": {"total": {"p50": 9.5}}} and out["environment"] == {"x": 1}


@pytest.mark.parametrize("bad", [True])
def test_a_flagged_window_is_reported_as_throttled(bad: bool) -> None:
    result: dict[str, Any] = {"speed": speed_of(10.0)}
    out = merge_telemetry(result, {}, [sample(t, 3000.0, throttled=bad) for t in range(0, 10)], {})
    assert out["speed"]["latency_valid"] is False and out["telemetry"]["run"]["throttled"] is True


def test_the_telemetry_series_is_thinned_and_measured_from_the_first_repeat() -> None:
    samples = [
        {"t": 99.0 + i * 0.2, "temp_c": 50.0 + i, "clock_mhz": 3000.0, "cpu": 10.0, "throttled": False}
        for i in range(400)
    ]
    reps = [{"t_start": 100.0, "t_end": 130.0, "valid": True}, {"t_start": 140.0, "t_end": 170.0, "valid": False}]
    out = series(samples, reps, limit=50)
    assert len(out["t"]) <= 50 and out["t"][0] == pytest.approx(-1.0)  # a second of lead-in before the first repeat
    assert all(len(out[k]) == len(out["t"]) for k in ("temp_c", "clock_mhz", "cpu", "throttled"))
    assert out["repeats"] == [{"start": 0.0, "end": 30.0, "valid": True}, {"start": 40.0, "end": 70.0, "valid": False}]
    assert out["t"][-1] <= 71.0  # nothing after the last repeat but a second of tail


def test_the_series_is_part_of_the_run_telemetry() -> None:
    speed = speed_of(10.0)
    samples = [{"t": 1.0 * i, "temp_c": 60.0, "clock_mhz": 3000.0, "cpu": 5.0, "throttled": False} for i in range(20)]
    out = merge_telemetry({"speed": speed}, {"hz": 5}, samples, {})
    assert out["telemetry"]["series"]["repeats"][0]["valid"] is True
