from __future__ import annotations

from typing import Any

import pytest

from edgebench.drift import Thresholds, accuracy_delta, agreement, iou, measure, verdict
from edgebench.latency import compare, repeat_values, summary


def speed(*p50s: float, valid: list[bool] | None = None) -> dict[str, Any]:
    flags = valid or [True] * len(p50s)
    return {
        "repeats": [
            {"index": i, "valid": v, "stats": {"p50": p}} for i, (p, v) in enumerate(zip(p50s, flags, strict=True))
        ]
    }


def test_the_headline_is_the_mean_of_the_repeats_medians_with_an_interval() -> None:
    s = summary(speed(10.0, 12.0, 14.0))
    assert s is not None and s["p50_ms"] == 12.0 and s["n"] == 3 and s["wide"] and s["valid"]
    assert s["ci_half_width_ms"] == pytest.approx(4.303 * 2 / 3**0.5, abs=0.01) and s["fps"] == pytest.approx(1000 / 12)


def test_a_throttled_repeat_does_not_count_and_an_all_throttled_run_is_marked_invalid() -> None:
    s = summary(speed(10.0, 12.0, 90.0, valid=[True, True, False]))
    assert s is not None and s["p50_ms"] == 11.0 and s["valid_repeats"] == 2 and s["repeats"] == 3
    none_valid = summary(speed(10.0, 12.0, valid=[False, False]))
    assert none_valid is not None and none_valid["valid"] is False and none_valid["p50_ms"] == 11.0


def test_a_run_from_before_repeats_existed_is_one_repeat_with_no_interval() -> None:
    s = summary({"stages": {"total": {"p50": 9.5}}})
    assert s is not None and s["p50_ms"] == 9.5 and s["ci_half_width_ms"] is None and s["n"] == 1
    assert summary(None) is None and summary({}) is None and repeat_values({"stages": {}}) == ([], 0, 0)


def test_a_clear_speedup_is_significant_and_three_noisy_repeats_are_not() -> None:
    clear = compare(speed(20.0, 20.2, 19.8), speed(10.0, 10.1, 9.9))
    assert clear is not None and clear["significant"] is True and clear["speedup"] == pytest.approx(2.0)
    noisy = compare(speed(20.0, 24.0, 28.0), speed(19.0, 23.0, 27.0))
    assert noisy is not None and noisy["significant"] is False and noisy["speedup"] == pytest.approx(24 / 23)


def test_a_single_repeat_cannot_be_tested_and_says_why() -> None:
    one = compare(speed(20.0), speed(10.0))
    assert one is not None and one["significant"] is None and "at least 2" in one["note"]
    throttled = compare(speed(20.0, 21.0), speed(10.0, 11.0, valid=[False, False]))
    assert throttled is not None and throttled["significant"] is None and "throttled" in throttled["note"]
    assert compare(None, speed(1.0, 2.0)) is None


def box(x: float, y: float, cls: int = 0, w: float = 0.2, score: float = 0.9) -> list[float]:
    return [x, y, x + w, y + w, score, float(cls)]


NAMES = ["chips", "biscuit"]


def test_iou_of_identical_half_and_disjoint_boxes() -> None:
    assert iou([0, 0, 1, 1], [0, 0, 1, 1]) == 1.0 and iou([0, 0, 1, 1], [0.5, 0, 1.5, 1]) == pytest.approx(1 / 3)
    assert iou([0, 0, 1, 1], [2, 2, 3, 3]) == 0.0 and iou([0, 0, 0, 0], [0, 0, 0, 0]) == 0.0


def test_identical_predictions_agree_completely() -> None:
    preds = {"0": [box(0.1, 0.1), box(0.5, 0.5, 1)], "1": [box(0.2, 0.2)]}
    a = agreement(preds, preds, NAMES, NAMES)
    assert a["mean_box_iou"] == 1.0 and a["missed"] == 0 and a["class_flips"] == 0 and a["matched"] == 3


def test_a_small_shift_lowers_agreement_a_missed_object_counts_as_zero_and_a_flip_is_counted() -> None:
    base = {"0": [box(0.1, 0.1), box(0.6, 0.6, 1)], "1": [box(0.3, 0.3)]}
    other = {"0": [box(0.12, 0.1, 0), box(0.6, 0.6, 0)]}  # picture 1 found nothing; the second box has the wrong class
    a = agreement(base, other, NAMES, NAMES)
    assert a["matched"] == 2 and a["missed"] == 1 and a["class_flips"] == 1 and a["variant_detections"] == 2
    first = iou(box(0.1, 0.1), box(0.12, 0.1))
    assert a["mean_box_iou"] == pytest.approx((first + 1.0) / 3)


def test_classes_are_compared_by_name_not_by_index() -> None:
    base = {"0": [box(0.1, 0.1, 0)]}
    same = agreement(
        base, {"0": [box(0.1, 0.1, 1)]}, ["chips", "biscuit"], ["biscuit", "chips"]
    )  # index 1 is "chips" there
    assert same["class_flips"] == 0


def test_a_variant_that_finds_nothing_fails_the_gate_whatever_the_thresholds() -> None:
    """The INT8 ONNX file that loads, runs fast and returns zero detections (docs/phase-0-verdict.md)."""
    base = {str(i): [box(0.1, 0.1), box(0.5, 0.5, 1)] for i in range(5)}
    d = measure(base, {}, NAMES, NAMES, base_accuracy=None, other_accuracy=None)
    assert d["variant_detections"] == 0 and d["mean_box_iou"] == 0.0
    v = verdict(d, Thresholds(max_map_drop=1.0, min_agreement=0.0))
    assert v["passed"] is False and "finds nothing" in v["reasons"][0]


def test_a_faithful_variant_passes_and_a_drifting_one_fails_on_agreement() -> None:
    base = {str(i): [box(0.1, 0.1)] for i in range(10)}
    assert verdict(measure(base, base, NAMES, NAMES, base_accuracy=None, other_accuracy=None))["passed"]
    shifted = {str(i): [box(0.14, 0.1)] for i in range(10)}  # IoU about 0.67 against 0.85 required
    v = verdict(measure(base, shifted, NAMES, NAMES, base_accuracy=None, other_accuracy=None))
    assert not v["passed"] and "agree" in v["reasons"][0]
    assert verdict(
        measure(base, shifted, NAMES, NAMES, base_accuracy=None, other_accuracy=None), Thresholds(min_agreement=0.5)
    )["passed"]  # configurable


def acc(map50: float, ap: dict[str, float]) -> dict[str, Any]:
    return {
        "available": True,
        "map50": map50,
        "map50_95": map50 / 2,
        "per_class": {k: {"ap50": v} for k, v in ap.items()},
    }


def test_the_map_drop_gate_uses_the_configured_threshold() -> None:
    base, other = acc(0.80, {"chips": 0.9, "biscuit": 0.7}), acc(0.76, {"chips": 0.85, "biscuit": 0.67})
    d = accuracy_delta(base, other)
    assert d["map50_delta"] == pytest.approx(-0.04) and d["per_class_ap50_delta"]["chips"] == pytest.approx(-0.05)
    assert verdict({**d, "agreement_available": False}, Thresholds(max_map_drop=0.02))["passed"] is False
    assert verdict({**d, "agreement_available": False}, Thresholds(max_map_drop=0.05))["passed"] is True


def test_without_labels_or_predictions_the_missing_parts_are_none_not_zero() -> None:
    d = measure(None, None, NAMES, NAMES, base_accuracy={"available": False}, other_accuracy=acc(0.5, {}))
    assert d["map50_delta"] is None and d["agreement_available"] is False
    assert verdict(d)["passed"]  # nothing measured is nothing to fail on; the UI says "not measured"
