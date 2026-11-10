"""The benchmark process end to end, with a runtime that knows the right answers (only the plumbing is tested)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from edgebench import dataset_import
from PIL import Image

from edgebench_agent import bench
from edgebench_agent.dataset import unpack
from edgebench_agent.decode import letterbox
from edgebench_agent.runtimes import Runner

COLOURS = [(250, 10, 10), (10, 250, 10), (10, 10, 250), (250, 250, 10)]
SIZE = (200, 100)
# class, centre x, centre y, width, height (relative) for picture n; every picture holds one box
BOXES = [(0, 0.3, 0.5, 0.2, 0.4), (1, 0.7, 0.5, 0.2, 0.4), (0, 0.5, 0.3, 0.4, 0.2), (1, 0.5, 0.7, 0.4, 0.2)]


def make_dataset(tmp_path: Path, labelled: bool = True, names: list[str] | None = None) -> Path:
    src = tmp_path / "src"
    (src / "images").mkdir(parents=True)
    (src / "labels").mkdir()
    for i, colour in enumerate(COLOURS):
        Image.new("RGB", SIZE, colour).save(src / "images" / f"{i}.jpg", quality=100)
        if labelled:
            (src / "labels" / f"{i}.txt").write_text(" ".join(str(v) for v in BOXES[i]))
    (src / "data.yaml").write_text("names: [" + ", ".join(names or ["chips", "biscuit"]) + "]\n")
    zip_path = tmp_path / "set.zip"
    dataset_import.import_directory(src, zip_path)
    return unpack(zip_path, tmp_path / "unpacked")


class Oracle(Runner):
    """Looks at the picture's colour and answers with the true box (or a deliberately wrong class)."""

    def __init__(self, classes: int = 2, wrong: bool = False) -> None:
        self.classes, self.wrong = classes, wrong
        self.calls = 0

    def run(self, blob: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
        self.calls += 1
        centre = (blob[0, :, 320, 320] * 255).round().astype(int).tolist()
        n = min(range(4), key=lambda i: sum(abs(a - b) for a, b in zip(COLOURS[i], centre, strict=True)))
        cls, cx, cy, w, h = BOXES[n]
        scale, pad_y = 640 / SIZE[0], (640 - SIZE[1] * 640 / SIZE[0]) / 2
        out = np.zeros((1, 4 + self.classes, 1), dtype=np.float32)
        out[0, :4, 0] = [cx * SIZE[0] * scale, cy * SIZE[1] * scale + pad_y, w * SIZE[0] * scale, h * SIZE[1] * scale]
        out[0, 4 + ((cls + 1) % 2 if self.wrong else cls), 0] = 0.9
        return out


def spec(folder: Path, **kw: Any) -> dict[str, Any]:
    return {
        "kind": "onnx",
        "model_path": "unused",
        "imgsz": 640,
        "threads": 1,
        "dataset_dir": str(folder),
        "model_names": ["chips", "biscuit"],
        "dataset_names_generic": False,
        "conf": 0.001,
        "iou": 0.7,
        "max_det": 300,
        "warmup": 2,
        "iterations": 6,
        "accuracy": True,
        **kw,
    }


@pytest.fixture
def oracle(monkeypatch: pytest.MonkeyPatch) -> Oracle:
    runner = Oracle()
    monkeypatch.setattr(bench, "load_runner", lambda *_: runner)
    return runner


def test_a_model_that_knows_the_answers_scores_perfectly_through_the_whole_path(tmp_path: Path, oracle: Oracle) -> None:
    result = bench.run(spec(make_dataset(tmp_path)))
    assert result["ok"]
    acc = result["accuracy"]
    assert acc["available"] and acc["images"] == 4 and acc["class_mapping"] == "by name"
    assert acc["map50"] == pytest.approx(1.0, abs=0.01) and acc["map50_95"] > 0.9
    assert set(acc["per_class"]) == {"chips", "biscuit"} and acc["unmapped_classes"] == []
    assert acc["confusion"]["labels"] == ["chips", "biscuit", "background"]
    assert acc["confusion"]["matrix"] == [[2, 0, 0], [0, 2, 0], [0, 0, 0]]


def test_the_speed_pass_times_each_stage_and_counts_what_it_was_asked_to(tmp_path: Path, oracle: Oracle) -> None:
    result = bench.run(spec(make_dataset(tmp_path), accuracy=False, warmup=3, iterations=10))
    stages = result["speed"]["stages"]
    assert set(stages) == {"preprocess", "inference", "postprocess", "total"}
    assert len(result["speed"]["total_ms"]) == 10 and result["speed"]["pictures_cycled"] == 4
    assert all(s["p50"] <= s["p95"] <= s["max"] and s["min"] > 0 for s in stages.values())
    assert stages["total"]["mean"] >= stages["inference"]["mean"]
    assert result["accuracy"] == {"available": False, "note": "not requested"}
    assert result["load_ms"] >= 0 and result["first_inference_ms"] >= 0
    assert oracle.calls == 1 + 3 + 10  # the first call, then warm-up and the timed rounds: nothing hidden


def test_a_wrong_answer_scores_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bench, "load_runner", lambda *_: Oracle(wrong=True))
    acc = bench.run(spec(make_dataset(tmp_path)))["accuracy"]
    assert acc["map50"] == 0.0 and acc["recall"] == 0.0


def test_a_dataset_without_labels_runs_for_speed_and_says_accuracy_is_not_available(
    tmp_path: Path, oracle: Oracle
) -> None:
    result = bench.run(spec(make_dataset(tmp_path, labelled=False)))
    assert result["ok"] and result["accuracy"] == {"available": False, "note": "n/a (no labels)"}
    assert result["speed"]["stages"]["total"]["p50"] > 0


def test_classes_are_matched_by_name_so_a_different_order_does_not_matter(tmp_path: Path, oracle: Oracle) -> None:
    # the dataset lists biscuit first; the model lists chips first. Labels say class 0 = biscuit there.
    folder = make_dataset(tmp_path, names=["biscuit", "chips"])
    mapping, unmapped, how = bench.class_map(["biscuit", "chips"], ["chips", "biscuit"], generic=False)
    assert mapping == {0: 1, 1: 0} and unmapped == [] and how == "by name"
    assert bench.run(spec(folder))["accuracy"]["class_mapping"] == "by name"


def test_a_class_the_model_does_not_have_is_reported_and_left_out(tmp_path: Path, oracle: Oracle) -> None:
    mapping, unmapped, _ = bench.class_map(["chips", "dairy milk"], ["chips", "biscuit"], generic=False)
    assert mapping == {0: 0} and unmapped == ["dairy milk"]
    folder = make_dataset(tmp_path, names=["chips", "dairy milk"])
    acc = bench.run(spec(folder))["accuracy"]
    assert acc["unmapped_classes"] == ["dairy milk"] and set(acc["per_class"]) == {"chips"}


def test_a_dataset_without_names_is_matched_by_position_and_says_so() -> None:
    mapping, unmapped, how = bench.class_map(["class_0", "class_1", "class_2"], ["chips", "biscuit"], generic=True)
    assert mapping == {0: 0, 1: 1} and unmapped == ["class_2"] and "by position" in how


def test_a_model_whose_output_does_not_fit_its_card_fails_with_a_clear_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bench, "load_runner", lambda *_: Oracle(classes=3))
    result = bench.run(spec(make_dataset(tmp_path)))
    assert result["ok"] is False and "outputs 3 classes but its card lists 2" in result["error"]


def test_the_letterbox_used_by_the_oracle_is_the_one_the_benchmark_uses() -> None:
    _, lb = letterbox(np.zeros((SIZE[1], SIZE[0], 3), dtype=np.uint8), 640)
    assert (lb.scale, lb.pad_x, lb.pad_y) == (3.2, 0, 160)


def test_a_run_can_be_pinned_to_cpus_and_says_which(tmp_path: Path, oracle: Oracle) -> None:
    import psutil

    process = psutil.Process()
    if not hasattr(process, "cpu_affinity"):
        pytest.skip("no CPU affinity on this system")
    before = process.cpu_affinity()
    try:
        result = bench.run(spec(make_dataset(tmp_path), accuracy=False, iterations=3, cpu_list=[before[0]]))
        assert result["runtime"]["cpus"] == [before[0]]
    finally:
        process.cpu_affinity(before)  # the test process is not left pinned
    assert bench.run(spec(make_dataset(tmp_path / "again"), accuracy=False, iterations=3))["runtime"]["cpus"] is None


def test_pinning_to_no_cpus_means_not_pinned() -> None:
    assert bench.pin_to_cpus(None) is None and bench.pin_to_cpus([]) is None


def test_every_picture_keeps_its_detections_for_inspection_and_the_overlap_is_measured(
    tmp_path: Path, oracle: Oracle
) -> None:
    result = bench.run(spec(make_dataset(tmp_path), accuracy=True))
    pictures = result["predictions"]["pictures"]
    assert set(pictures) == {"0", "1", "2", "3"} and result["predictions"]["min_confidence"] == 0.25
    for n, boxes in pictures.items():
        cls, cx, cy, w, h = BOXES[int(n)]
        ((x1, y1, x2, y2, score, got_cls),) = boxes
        assert got_cls == cls and score == pytest.approx(0.9, abs=0.001)
        assert [x1, y1, x2, y2] == pytest.approx(
            [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], abs=0.01
        )  # relative boxes
    assert result["accuracy"]["mean_iou"] == pytest.approx(1.0, abs=0.02)  # the oracle's boxes are the real ones


def test_pictures_without_annotations_still_show_what_the_model_found(tmp_path: Path, oracle: Oracle) -> None:
    result = bench.run(spec(make_dataset(tmp_path, labelled=False)))
    assert result["accuracy"] == {"available": False, "note": "n/a (no labels)"}
    assert len(result["predictions"]["pictures"]) == 4  # the speed-only dataset can still be inspected
    assert bench.run(spec(make_dataset(tmp_path / "again"), accuracy=False))["predictions"]["pictures"] == {}
