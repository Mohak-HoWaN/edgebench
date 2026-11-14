"""Detection accuracy: mAP50, mAP50-95, precision, recall, F1, per-class AP and a confusion matrix.

The arithmetic follows Ultralytics' validator (greedy one-to-one matching per IoU threshold, 101-point interpolated AP,
precision / recall / F1 read at the confidence that maximises smoothed mean F1), so the numbers can be checked against
``model.val()``. Classes are mean-averaged over the classes that have ground truth, as there.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray

IOU_THRESHOLDS = np.linspace(0.5, 0.95, 10)
EPS = 1e-16


def box_iou(a: NDArray[np.floating], b: NDArray[np.floating]) -> NDArray[np.float64]:
    """Pairwise IoU of ``(n, 4)`` and ``(m, 4)`` xyxy boxes, shape ``(n, m)``."""
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    lt = np.maximum(a[:, None, :2], b[None, :, :2])
    rb = np.minimum(a[:, None, 2:], b[None, :, 2:])
    inter = np.clip(rb - lt, 0, None).prod(2)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return inter / (area_a[:, None] + area_b[None] - inter + EPS)  # type: ignore[no-any-return]


def match_predictions(
    pred_cls: NDArray[np.integer],
    true_cls: NDArray[np.integer],
    iou: NDArray[np.floating],
) -> NDArray[np.bool_]:
    """For each prediction and each IoU threshold: is it a true positive? One prediction per truth, best IoU first."""
    correct = np.zeros((len(pred_cls), len(IOU_THRESHOLDS)), dtype=bool)
    if len(pred_cls) == 0 or len(true_cls) == 0:
        return correct
    iou = iou * (true_cls[:, None] == pred_cls[None, :])  # a box only matches a truth of the same class
    for i, thr in enumerate(IOU_THRESHOLDS):
        gt_idx, det_idx = np.nonzero(iou >= thr)
        if len(gt_idx) == 0:
            continue
        matches = np.stack([gt_idx, det_idx], axis=1)
        if len(matches) > 1:
            matches = matches[iou[matches[:, 0], matches[:, 1]].argsort()[::-1]]
            matches = matches[np.unique(matches[:, 1], return_index=True)[1]]
            matches = matches[np.unique(matches[:, 0], return_index=True)[1]]
        correct[matches[:, 1], i] = True
    return correct


def compute_ap(recall: NDArray[np.float64], precision: NDArray[np.float64]) -> float:
    """Area under the precision envelope, sampled at 101 recall points (COCO style)."""
    mrec = np.concatenate(([0.0], recall, [1.0]))
    mpre = np.concatenate(([1.0], precision, [0.0]))
    mpre = np.flip(np.maximum.accumulate(np.flip(mpre)))
    x = np.linspace(0, 1, 101)
    trapezoid = getattr(np, "trapezoid", None) or np.trapz  # numpy 2 renamed it
    return float(trapezoid(np.interp(x, mrec, mpre), x))


def _smooth(y: NDArray[np.float64], fraction: float = 0.1) -> NDArray[np.float64]:
    nf = round(len(y) * fraction * 2) // 2 * 2 + 1
    padded = np.concatenate((np.ones(nf // 2) * y[0], y, np.ones(nf // 2) * y[-1]))
    return np.convolve(padded, np.ones(nf) / nf, mode="valid")


@dataclass
class Metrics:
    map50: float
    map50_95: float
    precision: float
    recall: float
    f1: float
    confidence_at_best_f1: float
    per_class: dict[int, dict[str, float]]  # class index -> {ap50, ap50_95, images_with_truth, instances, predictions}
    mean_iou: float = 0.0  # average overlap of the boxes that were matched to a real object (at confidence 0.25)
    # Precision, recall and F1 at 51 confidence cut-offs (overall and per class index), for the curve charts
    curves: dict[str, Any] = field(default_factory=dict)
    # How many detections fell in each of 20 equal confidence bins from 0 to 1, for the score-distribution chart
    score_hist: list[int] = field(default_factory=list)


@dataclass
class Accumulator:
    """Collects one image at a time, then ``finish()`` computes the numbers."""

    num_classes: int
    tp: list[NDArray[np.bool_]] = field(default_factory=list)
    conf: list[NDArray[np.float64]] = field(default_factory=list)
    pred_cls: list[NDArray[np.int64]] = field(default_factory=list)
    target_cls: list[NDArray[np.int64]] = field(default_factory=list)
    confusion: NDArray[np.int64] = field(init=False)
    images_with_class: NDArray[np.int64] = field(init=False)
    iou_sum: float = 0.0
    iou_count: int = 0

    def __post_init__(self) -> None:
        self.confusion = np.zeros((self.num_classes + 1, self.num_classes + 1), dtype=np.int64)  # [true, predicted]
        self.images_with_class = np.zeros(self.num_classes, dtype=np.int64)

    def add(
        self,
        dets: NDArray[np.floating],
        truth_boxes: NDArray[np.floating],
        truth_cls: NDArray[np.integer],
    ) -> None:
        """``dets``: ``(n, 6)`` x1 y1 x2 y2 score class. Truth: boxes ``(m, 4)``, classes ``(m,)``, same pixels."""
        pred_cls = dets[:, 5].astype(np.int64)
        iou = box_iou(truth_boxes, dets[:, :4])
        self.tp.append(match_predictions(pred_cls, truth_cls, iou))
        self.conf.append(dets[:, 4].astype(np.float64))
        self.pred_cls.append(pred_cls)
        self.target_cls.append(truth_cls.astype(np.int64))
        for c in np.unique(truth_cls):
            self.images_with_class[int(c)] += 1
        self._confuse(dets, truth_boxes, truth_cls, iou)

    def _confuse(
        self,
        dets: NDArray[np.floating],
        truth_boxes: NDArray[np.floating],
        truth_cls: NDArray[np.integer],
        iou: NDArray[np.float64],
        conf: float = 0.25,
        iou_threshold: float = 0.45,
    ) -> None:
        n = self.num_classes
        keep = dets[:, 4] > conf
        dets, iou = dets[keep], iou[:, keep]
        det_cls = dets[:, 5].astype(np.int64)
        matched_gt: set[int] = set()
        matched_det: set[int] = set()
        gt_idx, det_idx = np.nonzero(iou > iou_threshold)
        if len(gt_idx):
            pairs = np.stack([gt_idx, det_idx, iou[gt_idx, det_idx]], axis=1)
            pairs = pairs[pairs[:, 2].argsort()[::-1]]
            pairs = pairs[np.unique(pairs[:, 1], return_index=True)[1]]
            pairs = pairs[pairs[:, 2].argsort()[::-1]]
            pairs = pairs[np.unique(pairs[:, 0], return_index=True)[1]]
            for g, d, overlap in pairs:
                self.confusion[int(truth_cls[int(g)]), int(det_cls[int(d)])] += 1
                self.iou_sum += float(overlap)
                self.iou_count += 1
                matched_gt.add(int(g))
                matched_det.add(int(d))
        for g in range(len(truth_cls)):
            if g not in matched_gt:
                self.confusion[int(truth_cls[g]), n] += 1  # missed: predicted as background
        for d in range(len(det_cls)):
            if d not in matched_det:
                self.confusion[n, int(det_cls[d])] += 1  # invented: truth was background

    def finish(self) -> Metrics | None:
        """None when there is no ground truth at all."""
        target = np.concatenate(self.target_cls) if self.target_cls else np.zeros(0, dtype=np.int64)
        classes = np.unique(target)
        if len(classes) == 0:
            return None
        tp = np.concatenate(self.tp) if self.tp else np.zeros((0, len(IOU_THRESHOLDS)), dtype=bool)
        conf = np.concatenate(self.conf) if self.conf else np.zeros(0)
        pred = np.concatenate(self.pred_cls) if self.pred_cls else np.zeros(0, dtype=np.int64)
        order = np.argsort(-conf, kind="stable")
        tp, conf, pred = tp[order], conf[order], pred[order]
        px = np.linspace(0, 1, 1000)
        ap = np.zeros((len(classes), len(IOU_THRESHOLDS)))
        p_curve = np.zeros((len(classes), 1000))
        r_curve = np.zeros((len(classes), 1000))
        for ci, c in enumerate(classes):
            sel = pred == c
            n_l, n_p = int((target == c).sum()), int(sel.sum())
            if n_p == 0 or n_l == 0:
                continue
            fpc = (~tp[sel]).cumsum(0)
            tpc = tp[sel].cumsum(0)
            recall = tpc / (n_l + EPS)
            precision = tpc / (tpc + fpc)
            r_curve[ci] = np.interp(-px, -conf[sel], recall[:, 0], left=0)
            p_curve[ci] = np.interp(-px, -conf[sel], precision[:, 0], left=1)
            for j in range(len(IOU_THRESHOLDS)):
                ap[ci, j] = compute_ap(recall[:, j], precision[:, j])
        f1_curve = 2 * p_curve * r_curve / (p_curve + r_curve + EPS)
        best = int(_smooth(f1_curve.mean(0), 0.1).argmax())
        grid = [*range(0, 1000, 20), 999]

        def thin(curve: NDArray[np.float64]) -> list[float]:
            return [round(float(curve[i]), 4) for i in grid]

        curves = {
            "conf": [round(float(px[i]), 3) for i in grid],
            "all": {"precision": thin(p_curve.mean(0)), "recall": thin(r_curve.mean(0)), "f1": thin(f1_curve.mean(0))},
            "per_class": {
                int(c): {"precision": thin(p_curve[i]), "recall": thin(r_curve[i]), "f1": thin(f1_curve[i])}
                for i, c in enumerate(classes)
            },
        }
        per_class = {
            int(c): {
                "ap50": float(ap[i, 0]),
                "ap50_95": float(ap[i].mean()),
                "instances": float((target == c).sum()),
                "images": float(self.images_with_class[int(c)]),
                "predictions": float((pred == c).sum()),
            }
            for i, c in enumerate(classes)
        }
        return Metrics(
            map50=float(ap[:, 0].mean()),
            map50_95=float(ap.mean()),
            precision=float(p_curve[:, best].mean()),
            recall=float(r_curve[:, best].mean()),
            f1=float(f1_curve[:, best].mean()),
            confidence_at_best_f1=float(px[best]),
            per_class=per_class,
            mean_iou=self.iou_sum / self.iou_count if self.iou_count else 0.0,
            curves=curves,
            score_hist=[int(n) for n in np.histogram(conf, bins=20, range=(0.0, 1.0))[0]],
        )
