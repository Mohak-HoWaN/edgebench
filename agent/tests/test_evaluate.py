from __future__ import annotations

import numpy as np
import pytest

from edgebench_agent.evaluate import IOU_THRESHOLDS, Accumulator, box_iou, compute_ap, match_predictions


def dets(*rows: tuple[float, float, float, float, float, int]) -> np.ndarray:
    return np.array(rows, dtype=np.float64).reshape(-1, 6)


def boxes(*rows: tuple[float, float, float, float]) -> np.ndarray:
    return np.array(rows, dtype=np.float64).reshape(-1, 4)


def test_iou_of_known_boxes() -> None:
    a = boxes((0, 0, 10, 10))
    b = boxes((0, 0, 10, 10), (5, 0, 15, 10), (20, 20, 30, 30))
    assert box_iou(a, b)[0] == pytest.approx([1.0, 1 / 3, 0.0], abs=1e-9)
    assert box_iou(a, boxes()).shape == (1, 0)


def test_a_box_matches_at_every_threshold_it_reaches_and_not_beyond() -> None:
    iou = np.array([[0.62]])
    correct = match_predictions(np.array([0]), np.array([0]), iou)
    assert correct[0].tolist() == [t <= 0.62 for t in IOU_THRESHOLDS]  # 0.50, 0.55 and 0.60 only


def test_a_box_of_the_wrong_class_never_matches_and_a_truth_is_used_once() -> None:
    wrong_class = match_predictions(np.array([1]), np.array([0]), np.array([[0.99]]))
    assert not wrong_class.any()
    # two predictions on one truth: the higher-scored one (listed first) takes it, the other is a false positive
    iou = np.array([[0.7, 0.9]])
    correct = match_predictions(np.array([0, 0]), np.array([0]), iou)
    assert correct[:, 0].tolist() == [True, False]


def test_ap_of_a_perfect_ranking_is_one_and_of_a_half_wrong_one_is_lower() -> None:
    assert compute_ap(np.array([0.5, 1.0]), np.array([1.0, 1.0])) == pytest.approx(1.0, abs=0.01)
    # rank: hit, miss, hit  ->  recall 0.5, 0.5, 1.0 and precision 1, 0.5, 0.667: area is about 0.5 * 1 + 0.5 * 0.667
    ap = compute_ap(np.array([0.5, 0.5, 1.0]), np.array([1.0, 0.5, 2 / 3]))
    assert ap == pytest.approx(0.8333, abs=0.01)


def perfect_image(acc: Accumulator) -> None:
    truth = boxes((10, 10, 50, 50), (60, 60, 90, 90))
    acc.add(dets((10, 10, 50, 50, 0.9, 0), (60, 60, 90, 90, 0.8, 1)), truth, np.array([0, 1]))


def test_perfect_detections_score_one_everywhere() -> None:
    acc = Accumulator(2)
    perfect_image(acc)
    perfect_image(acc)
    m = acc.finish()
    assert m is not None
    assert m.map50 == pytest.approx(1.0, abs=0.01) and m.map50_95 == pytest.approx(1.0, abs=0.01)
    assert m.precision == pytest.approx(1.0, abs=0.01) and m.recall == pytest.approx(1.0, abs=0.01)
    assert m.per_class[0]["instances"] == 2 and m.per_class[1]["images"] == 2
    assert acc.confusion.tolist() == [[2, 0, 0], [0, 2, 0], [0, 0, 0]]


def test_a_missed_object_and_a_made_up_one_show_in_the_numbers_and_the_confusion_matrix() -> None:
    acc = Accumulator(2)
    truth = boxes((10, 10, 50, 50), (60, 60, 90, 90))
    # class 0 found, class 1 missed, and a class 0 box where nothing is
    acc.add(dets((10, 10, 50, 50, 0.9, 0), (0, 70, 20, 99, 0.6, 0)), truth, np.array([0, 1]))
    m = acc.finish()
    assert m is not None
    assert m.per_class[1]["ap50"] == 0.0  # nothing was predicted for class 1
    assert m.map50 == pytest.approx(0.5, abs=0.01)
    assert acc.confusion[1, 2] == 1  # truth class 1, predicted background
    assert acc.confusion[2, 0] == 1  # truth background, predicted class 0


def test_a_localisation_error_hurts_map50_95_more_than_map50() -> None:
    acc = Accumulator(1)
    # shifted by 12 of 40 pixels: IoU 0.54, right at 0.5 and wrong from 0.55 up
    acc.add(dets((22, 10, 62, 50, 0.9, 0)), boxes((10, 10, 50, 50)), np.array([0]))
    m = acc.finish()
    assert m is not None and m.map50 == pytest.approx(1.0, abs=0.01) and m.map50_95 < 0.15


def test_no_ground_truth_gives_no_metrics() -> None:
    acc = Accumulator(2)
    acc.add(dets((1, 1, 5, 5, 0.9, 0)), boxes(), np.array([], dtype=np.int64))
    assert acc.finish() is None


def test_a_picture_with_nothing_in_it_and_no_detections_is_fine() -> None:
    acc = Accumulator(1)
    acc.add(dets(), boxes(), np.array([], dtype=np.int64))
    acc.add(dets((10, 10, 50, 50, 0.9, 0)), boxes((10, 10, 50, 50)), np.array([0]))
    m = acc.finish()
    assert m is not None and m.map50 == pytest.approx(1.0, abs=0.01)


def test_the_curves_and_the_score_histogram_are_recorded_thin_enough_to_store() -> None:
    acc = Accumulator(2)
    perfect_image(acc)
    perfect_image(acc)
    acc.add(dets((0, 0, 10, 10, 0.2, 0)), boxes(), np.zeros(0, dtype=np.int64))  # a made-up detection with a low score
    m = acc.finish()
    assert m is not None
    assert len(m.curves["conf"]) == 51 and m.curves["conf"][0] == 0.0 and m.curves["conf"][-1] == 1.0
    assert set(m.curves["all"]) == {"precision", "recall", "f1"} and all(len(v) == 51 for v in m.curves["all"].values())
    assert set(m.curves["per_class"]) == {0, 1} and len(m.curves["per_class"][0]["recall"]) == 51
    assert m.curves["all"]["recall"][0] == pytest.approx(1.0, abs=0.01)  # nothing is cut off at confidence 0
    assert len(m.score_hist) == 20 and sum(m.score_hist) == 5  # four confident detections and the made-up one
    assert m.score_hist[4] == 1  # the 0.2 detection sits in the 0.20 to 0.25 bin
