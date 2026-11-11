from __future__ import annotations

import pytest

from edgebench.sweep import Subject, expand, median, seconds_for_run


def subject(label: str = "ONNX FP32", variant_id: int | None = 1, native: int = 640, **sizes: int) -> Subject:
    return Subject(1, variant_id, label, native, {native: variant_id or 0, **{int(k[1:]): v for k, v in sizes.items()}})


def test_every_combination_becomes_a_run_and_the_count_is_the_product() -> None:
    kept, pruned = expand([subject(), subject("OpenVINO FP32", 2)], [1, 2, 4, 8], [None], [None], 16)
    assert len(kept) == 8 and not pruned
    assert sorted({c.threads for c in kept}) == [1, 2, 4, 8]


def test_more_threads_than_the_device_has_are_pruned_with_the_reason() -> None:
    kept, pruned = expand([subject()], [1, 4, 32], [None], [None], 8)
    assert [c.threads for c in kept] == [1, 4]
    assert len(pruned) == 1 and pruned[0].threads == 32 and "32 threads do not fit" in pruned[0].reason
    assert "8 CPUs" in pruned[0].reason


def test_threads_must_fit_on_the_pinned_cpus_not_on_the_whole_device() -> None:
    kept, pruned = expand([subject()], [1, 2, 4], [[0, 1]], [None], 16)
    assert [c.threads for c in kept] == [1, 2] and "2 pinned CPUs" in pruned[0].reason
    assert kept[0].cpu_list == (0, 1)


def test_a_cpu_that_does_not_exist_prunes_every_run_that_names_it() -> None:
    kept, pruned = expand([subject()], [1], [[0, 1], [6, 9]], [None], 8)
    assert [c.cpu_list for c in kept] == [(0, 1)]
    assert "CPUs 0 to 7" in pruned[0].reason and pruned[0].cpu_list == (6, 9)


def test_a_size_with_no_finished_conversion_is_pruned_and_one_that_exists_runs_that_variant() -> None:
    kept, pruned = expand([subject(s416=7)], [1], [None], [None, 416, 512], 8)
    assert [(c.imgsz, c.variant_id) for c in kept] == [(640, 1), (416, 7)]
    assert len(pruned) == 1 and pruned[0].imgsz == 512 and "no finished conversion at 512 px" in pruned[0].reason
    assert kept[1].label == "ONNX FP32 at 416 px" and kept[0].label == "ONNX FP32"


def test_the_pytorch_baseline_only_runs_at_the_models_own_size() -> None:
    kept, pruned = expand([subject("PyTorch baseline", None)], [1], [None], [None, 416], 8)
    assert [c.imgsz for c in kept] == [640] and "own input size" in pruned[0].reason


def test_the_same_measurement_named_twice_is_run_once() -> None:
    kept, _ = expand([subject()], [2, 2], [[0, 1], [1, 0]], [None], 8)
    assert len(kept) == 1


def test_a_device_with_unknown_core_count_prunes_nothing_on_threads() -> None:
    kept, pruned = expand([subject()], [64], [None], [None], None)
    assert len(kept) == 1 and not pruned


def test_the_estimate_adds_the_load_the_accuracy_pass_and_the_timed_repeats() -> None:
    # 10 ms per inference: 3 s load + 100 pictures * 10 ms * 1.4 + 3 repeats * (20 + 200) * 10 ms = 3 + 1.4 + 6.6
    assert seconds_for_run(100, 10.0, 20, 200, 3, accuracy=True) == pytest.approx(11.0)
    assert seconds_for_run(100, 10.0, 20, 200, 3, accuracy=False) == pytest.approx(
        9.6
    )  # no accuracy pass, no picture reading


def test_the_median_of_earlier_timings_handles_odd_even_and_none() -> None:
    assert median([3.0, 1.0, 2.0]) == 2.0 and median([1.0, 4.0]) == 2.5 and median([]) is None
