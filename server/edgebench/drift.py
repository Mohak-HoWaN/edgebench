"""How far a converted variant has drifted from the ``.pt`` baseline, measured on the same dataset version.

Two kinds of number. *Accuracy* drift is the change in mAP (and per class). *Agreement* needs no labels: for every
detection the baseline made, how well the variant's best box overlaps it. A model that finds nothing scores 0 agreement,
which is how the accuracy gate catches the INT8 ONNX file that loads, runs fast and returns zero detections
(docs/phase-0-verdict.md).

Detections come from the per-picture predictions each run stored (confidence at least 0.25, at most 50 per picture), as
``[x1, y1, x2, y2, score, class]`` relative to the picture. Classes are compared by name.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MATCH_IOU = 0.5  # a variant box this close to a baseline box counts as the same detection


@dataclass(frozen=True)
class Thresholds:
    """The defaults come from one real measurement (yolo11n on COCO128, 128 calibration pictures; see STATE.md).

    OpenVINO INT8 lost 3.5 mAP points at agreement 0.83 and is worth keeping; ONNX INT8 lost 6.6 at 0.74 and is not.
    They are a starting point: set them in Settings for your own data and for how much loss you can accept.
    """

    max_map_drop: float = 0.05  # mAP@50 may fall by this much (absolute: 0.05 is five points)
    min_agreement: float = 0.80  # mean box agreement may not fall below this


DEFAULT_THRESHOLDS = Thresholds()


def iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def agreement(
    base: dict[str, list[list[float]]],
    other: dict[str, list[list[float]]],
    base_names: list[str],
    other_names: list[str],
) -> dict[str, Any]:
    """For each baseline detection, the IoU of the best variant box (0 below 0.5 or when none), and the class flips."""
    total = matched = flips = 0
    score_sum = 0.0
    for key, boxes in base.items():
        theirs = other.get(key) or []
        for box in boxes:
            total += 1
            best, best_box = 0.0, None
            for candidate in theirs:
                v = iou(box, candidate)
                if v > best:
                    best, best_box = v, candidate
            if best >= MATCH_IOU and best_box is not None:
                matched += 1
                score_sum += best
                a, b = base_names[int(box[5])], other_names[int(best_box[5])]
                flips += a.strip().lower() != b.strip().lower()
    return {
        "baseline_detections": total,
        "variant_detections": sum(len(v) for v in other.values()),
        "matched": matched,
        "missed": total - matched,
        "class_flips": flips,
        "mean_box_iou": score_sum / total if total else None,
    }


def accuracy_delta(base: dict[str, Any] | None, other: dict[str, Any] | None) -> dict[str, Any]:
    """Change in mAP and per-class AP@50 (variant minus baseline). None when a run has no labels to score against."""
    if not base or not other or not base.get("available") or not other.get("available"):
        return {"map50_delta": None, "map50_95_delta": None, "per_class_ap50_delta": None}
    per_class = {
        name: other["per_class"][name]["ap50"] - v["ap50"]
        for name, v in base.get("per_class", {}).items()
        if name in other.get("per_class", {})
    }
    return {
        "map50_delta": other["map50"] - base["map50"],
        "map50_95_delta": other["map50_95"] - base["map50_95"],
        "per_class_ap50_delta": per_class,
    }


def measure(
    base_predictions: dict[str, Any] | None,
    other_predictions: dict[str, Any] | None,
    base_names: list[str],
    other_names: list[str],
    *,
    base_accuracy: dict[str, Any] | None,
    other_accuracy: dict[str, Any] | None,
) -> dict[str, Any]:
    out: dict[str, Any] = accuracy_delta(base_accuracy, other_accuracy)
    if base_predictions is None or other_predictions is None:
        return {**out, "agreement_available": False}
    return {
        **out,
        "agreement_available": True,
        **agreement(base_predictions, other_predictions, base_names, other_names),
    }


def verdict(d: dict[str, Any], limits: Thresholds = DEFAULT_THRESHOLDS) -> dict[str, Any]:
    """Pass or fail, with the reasons. A variant that finds nothing the baseline found always fails."""
    reasons: list[str] = []
    if d.get("agreement_available"):
        if d["baseline_detections"] and d["variant_detections"] == 0:
            reasons.append("it finds nothing, where the baseline found objects")
        elif d["mean_box_iou"] is not None and d["mean_box_iou"] < limits.min_agreement:
            reasons.append(
                f"its boxes agree with the baseline's by {d['mean_box_iou']:.2f}, below {limits.min_agreement:.2f}"
            )
    if d.get("map50_delta") is not None and d["map50_delta"] < -limits.max_map_drop:
        reasons.append(
            f"mAP@50 fell by {-d['map50_delta'] * 100:.1f} points, more than {limits.max_map_drop * 100:.1f}"
        )
    return {"passed": not reasons, "reasons": reasons}
