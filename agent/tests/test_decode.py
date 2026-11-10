from __future__ import annotations

import numpy as np
import pytest

from edgebench_agent.decode import decode, letterbox, nms, to_blob, to_original


def raw_output(anchors: list[tuple[float, float, float, float, list[float]]]) -> np.ndarray:
    """(1, 4 + classes, anchors) from (cx, cy, w, h, [class scores]) rows."""
    return np.array([[cx, cy, w, h, *scores] for cx, cy, w, h, scores in anchors], dtype=np.float32).T[None]


def test_letterbox_fits_the_picture_and_pads_with_grey() -> None:
    rgb = np.full((100, 200, 3), 7, dtype=np.uint8)  # wide: padded top and bottom
    out, lb = letterbox(rgb, 640)
    assert out.shape == (640, 640, 3) and lb.scale == pytest.approx(3.2)
    assert (out[0, 0] == 114).all() and (out[320, 320] == 7).all()
    assert lb.pad_x == 0 and lb.pad_y == 160


def test_a_box_survives_the_trip_into_the_model_and_back() -> None:
    rgb = np.zeros((300, 400, 3), dtype=np.uint8)
    _, lb = letterbox(rgb, 640)
    # a box at (100, 50)-(300, 250) in picture pixels, as the model would report it in letterboxed pixels
    inside = np.array(
        [
            [
                100 * lb.scale + lb.pad_x,
                50 * lb.scale + lb.pad_y,
                300 * lb.scale + lb.pad_x,
                250 * lb.scale + lb.pad_y,
                0.9,
                0,
            ]
        ],
        dtype=np.float32,
    )
    back = to_original(inside, lb)
    assert back[0, :4] == pytest.approx([100, 50, 300, 250], abs=1e-3)
    outside = np.array([[-50, -50, 2000, 2000, 0.9, 0]], dtype=np.float32)
    assert to_original(outside, lb)[0, :4].tolist() == [0, 0, 400, 300]  # clipped to the picture


def test_the_blob_is_channels_first_float_in_zero_to_one() -> None:
    blob = to_blob(np.full((4, 4, 3), 255, dtype=np.uint8))
    assert blob.shape == (1, 3, 4, 4) and blob.dtype == np.float32 and blob.max() == 1.0


def test_nms_keeps_the_best_of_overlapping_boxes_and_all_the_separate_ones() -> None:
    b = np.array([[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]], dtype=np.float32)
    s = np.array([0.5, 0.9, 0.4], dtype=np.float32)
    assert nms(b, s, 0.5, 300) == [1, 2]  # the first two overlap at IoU 0.68
    assert nms(b, s, 0.7, 300) == [1, 0, 2]  # a looser threshold keeps both
    assert nms(b, s, 0.5, 1) == [1]


def test_decode_suppresses_duplicates_within_a_class_but_not_across_classes() -> None:
    same_spot = [(100, 100, 40, 40, [0.9, 0.0]), (101, 101, 40, 40, [0.8, 0.0]), (100, 100, 40, 40, [0.0, 0.7])]
    out = decode(raw_output(same_spot), conf=0.25, iou=0.5)
    assert sorted(out[:, 5].tolist()) == [0.0, 1.0] and out.shape == (2, 6)  # one box per class survives
    assert out[out[:, 5] == 0][0, 4] == pytest.approx(0.9)


def test_multi_label_reports_every_class_above_the_threshold_and_single_label_only_the_best() -> None:
    both = raw_output([(100, 100, 40, 40, [0.6, 0.5])])
    assert decode(both, conf=0.25, multi_label=True).shape[0] == 2
    single = decode(both, conf=0.25, multi_label=False)
    assert single.shape[0] == 1 and single[0, 5] == 0


def test_the_confidence_floor_and_the_detection_cap_apply() -> None:
    rows = [(20 + 30 * i, 20, 10, 10, [0.9 - 0.05 * i]) for i in range(10)]
    assert decode(raw_output(rows), conf=0.6, iou=0.7).shape[0] == 6  # 0.90 down to 0.65 pass, 0.60 does not
    assert decode(raw_output(rows), conf=0.001, iou=0.7, max_det=3).shape[0] == 3
    assert decode(raw_output([(10, 10, 5, 5, [0.0])]), conf=0.25).shape == (0, 6)
