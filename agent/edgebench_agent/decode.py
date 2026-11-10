"""The one preprocess / decode / NMS path every variant goes through (README rule 1).

If each runtime used its own post-processing, a drift number would measure NMS differences instead of quantization. The
model runtimes only turn a letterboxed image into the raw head output ``(1, 4 + classes, anchors)``; the rest is here.
The defaults mirror Ultralytics' validator (conf 0.001, IoU 0.7, 300 detections, multi-label), so mAP is comparable.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

try:  # Ultralytics resizes with OpenCV; use the same when it is there so the numbers can agree.
    import cv2
except ImportError:  # pragma: no cover - the Pi image may not carry OpenCV
    cv2 = None

PAD_VALUE = 114
MAX_WH = 7680  # offsets boxes by class so one NMS pass never merges two classes
MAX_CANDIDATES = 30000


@dataclass(frozen=True)
class Letterbox:
    """How an image was fitted into the square input: undo it to get boxes in original pixels."""

    scale: float
    pad_x: float
    pad_y: float
    width: int
    height: int


def letterbox(rgb: NDArray[np.uint8], size: int) -> tuple[NDArray[np.uint8], Letterbox]:
    """Fit an RGB image into ``size`` x ``size`` keeping its shape, padding with grey (what Ultralytics does)."""
    h, w = rgb.shape[:2]
    r = min(size / h, size / w)
    new_w, new_h = round(w * r), round(h * r)
    dw, dh = (size - new_w) / 2, (size - new_h) / 2
    if (new_w, new_h) != (w, h):
        if cv2 is not None:
            rgb = cv2.resize(rgb, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        else:
            from PIL import Image

            rgb = np.asarray(Image.fromarray(rgb).resize((new_w, new_h), Image.Resampling.BILINEAR))
    top, left = (
        round(dh - 0.1),
        round(dw - 0.1),
    )  # Ultralytics' rounding: the extra pixel of odd padding goes below/right
    out = np.full((size, size, 3), PAD_VALUE, dtype=np.uint8)
    out[top : top + new_h, left : left + new_w] = rgb
    return out, Letterbox(scale=r, pad_x=float(left), pad_y=float(top), width=w, height=h)


def to_blob(letterboxed: NDArray[np.uint8]) -> NDArray[np.float32]:
    """HWC uint8 RGB to a ``(1, 3, H, W)`` float32 blob in 0..1."""
    blob = np.ascontiguousarray(letterboxed.transpose(2, 0, 1)[None], dtype=np.float32)
    blob /= 255.0
    return blob


def iou_one_to_many(box: NDArray[np.float32], boxes: NDArray[np.float32]) -> NDArray[np.float32]:
    x1 = np.maximum(box[0], boxes[:, 0])
    y1 = np.maximum(box[1], boxes[:, 1])
    x2 = np.minimum(box[2], boxes[:, 2])
    y2 = np.minimum(box[3], boxes[:, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area = (box[2] - box[0]) * (box[3] - box[1])
    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    return np.asarray(inter / (area + areas - inter + 1e-9), dtype=np.float32)


def nms(
    boxes: NDArray[np.float32],
    scores: NDArray[np.float32],
    iou_threshold: float,
    max_keep: int,
) -> list[int]:
    """Greedy non-maximum suppression (a box survives when its IoU with every kept box is at most the threshold)."""
    order = np.argsort(-scores, kind="stable")
    keep: list[int] = []
    while order.size and len(keep) < max_keep:
        i = int(order[0])
        keep.append(i)
        if order.size == 1:
            break
        rest = order[1:]
        order = rest[iou_one_to_many(boxes[i], boxes[rest]) <= iou_threshold]
    return keep


def decode(
    raw: NDArray[np.floating],
    conf: float = 0.001,
    iou: float = 0.7,
    max_det: int = 300,
    multi_label: bool = True,
) -> NDArray[np.float32]:
    """Raw head output to detections ``(n, 6)``: x1, y1, x2, y2 (letterboxed pixels), score, class index.

    ``raw`` is ``(1, 4 + classes, anchors)`` or without the batch axis: centre-x, centre-y, width, height, then one
    sigmoid score per class (what the Ultralytics export produces for every format).
    """
    p = np.asarray(raw, dtype=np.float32)
    if p.ndim == 3:
        p = p[0]
    p = p.T  # (anchors, 4 + classes)
    scores = p[:, 4:]
    xywh = p[:, :4]
    xyxy = np.empty_like(xywh)
    xyxy[:, 0] = xywh[:, 0] - xywh[:, 2] / 2
    xyxy[:, 1] = xywh[:, 1] - xywh[:, 3] / 2
    xyxy[:, 2] = xywh[:, 0] + xywh[:, 2] / 2
    xyxy[:, 3] = xywh[:, 1] + xywh[:, 3] / 2
    if multi_label:
        anchor, cls = np.nonzero(scores > conf)
        boxes, conf_values = xyxy[anchor], scores[anchor, cls]
    else:
        cls = scores.argmax(1)
        best = scores[np.arange(len(scores)), cls]
        anchor = np.nonzero(best > conf)[0]
        boxes, conf_values, cls = xyxy[anchor], best[anchor], cls[anchor]
    if len(boxes) == 0:
        return np.zeros((0, 6), dtype=np.float32)
    if len(boxes) > MAX_CANDIDATES:
        top = np.argsort(-conf_values, kind="stable")[:MAX_CANDIDATES]
        boxes, conf_values, cls = boxes[top], conf_values[top], cls[top]
    keep = nms(boxes + cls[:, None].astype(np.float32) * MAX_WH, conf_values, iou, max_det)
    return np.concatenate(
        [boxes[keep], conf_values[keep, None], cls[keep, None].astype(np.float32)],
        axis=1,
    )


def to_original(dets: NDArray[np.float32], lb: Letterbox) -> NDArray[np.float32]:
    """Move boxes from the letterboxed input back to the original image's pixels, clipped to the image."""
    out = dets.copy()
    out[:, [0, 2]] = ((out[:, [0, 2]] - lb.pad_x) / lb.scale).clip(0, lb.width)
    out[:, [1, 3]] = ((out[:, [1, 3]] - lb.pad_y) / lb.scale).clip(0, lb.height)
    return out
