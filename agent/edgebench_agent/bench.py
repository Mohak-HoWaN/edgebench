"""One benchmark run, in its own process: ``python -m edgebench_agent.bench spec.json``.

A native runtime can crash the interpreter without a traceback (ncnn did, in Phase 0), so the agent never runs a model
in its own process: a crash here fails one run and the agent carries on. The child prints ``PROGRESS <0..1>`` lines and
ends with one ``RESULT <json>`` line.

Two passes over the pictures. The accuracy pass runs every labelled picture once. The speed pass then cycles pictures
for ``warmup`` untimed and ``iterations`` timed rounds, timing preprocess, inference and postprocess separately.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np

from .dataset import Dataset, Entry, load_rgb, open_dataset, truth_boxes
from .decode import decode, letterbox, to_blob, to_original
from .evaluate import Accumulator, Metrics
from .repeats import finalize, stats_ms
from .runtimes import Runner, Unavailable, load_runner, package_versions

NS = 1_000_000.0  # nanoseconds per millisecond
CYCLE_PICTURES = 16  # pictures kept in memory for the speed pass


def class_map(dataset_names: list[str], model_names: list[str], generic: bool) -> tuple[dict[int, int], list[str], str]:
    """Dataset class index -> model class index, by name (by position only if the dataset has no names)."""
    if generic:
        count = min(len(dataset_names), len(model_names))
        return (
            {i: i for i in range(count)},
            dataset_names[count:],
            "by position (the dataset has no class names)",
        )
    wanted = {name.strip().lower(): i for i, name in enumerate(model_names)}
    mapping: dict[int, int] = {}
    unmapped: list[str] = []
    for i, name in enumerate(dataset_names):
        j = wanted.get(name.strip().lower())
        if j is None:
            unmapped.append(name)
        else:
            mapping[i] = j
    return mapping, unmapped, "by name"


def one_picture(
    runner: Runner,
    rgb: np.ndarray[Any, Any],
    size: int,
    conf: float,
    iou: float,
    max_det: int,
) -> tuple[np.ndarray[Any, Any], tuple[int, int, int]]:
    """Run the shared path on one picture. Returns detections in picture pixels and (pre, inference, post) in ns."""
    t0 = time.perf_counter_ns()
    boxed, lb = letterbox(rgb, size)
    blob = to_blob(boxed)
    t1 = time.perf_counter_ns()
    raw = runner.run(blob)
    t2 = time.perf_counter_ns()
    dets = to_original(decode(raw, conf, iou, max_det), lb)
    t3 = time.perf_counter_ns()
    return dets, (t1 - t0, t2 - t1, t3 - t2)


PREVIEW_CONF = 0.25  # detections below this are not kept for the picture inspector
PREVIEW_PER_PICTURE = 50
PREVIEW_PICTURES = 3000


def preview_boxes(dets: np.ndarray[Any, Any], width: int, height: int) -> list[list[float]]:
    """The most confident detections of one picture as relative boxes [x1, y1, x2, y2, score, class] for drawing."""
    kept = dets[dets[:, 4] >= PREVIEW_CONF][:PREVIEW_PER_PICTURE]  # decode() returns them best first
    return [
        [
            round(float(x1) / width, 4),
            round(float(y1) / height, 4),
            round(float(x2) / width, 4),
            round(float(y2) / height, 4),
            round(float(s), 3),
            int(c),
        ]
        for x1, y1, x2, y2, s, c in kept
    ]


def accuracy_pass(
    runner: Runner,
    data: Dataset,
    spec: dict[str, Any],
    model_names: list[str],
    progress: Any,
) -> tuple[dict[str, Any], dict[str, list[list[float]]]]:
    """Run every picture once. Annotated pictures are scored; every picture's detections are kept for inspection."""
    mapping, unmapped, how = class_map(data.names, model_names, bool(spec.get("dataset_names_generic")))
    acc = Accumulator(len(model_names))
    labelled = 0
    predictions: dict[str, list[list[float]]] = {}
    for n, entry in enumerate(data.entries):
        dets, _ = one_picture(runner, load_rgb(entry.path), spec["imgsz"], spec["conf"], spec["iou"], spec["max_det"])
        if n < PREVIEW_PICTURES:
            predictions[str(n)] = preview_boxes(dets, entry.width, entry.height)
        if entry.labels is not None:
            boxes, cls = truth_boxes(entry)
            keep = np.array([c in mapping for c in cls], dtype=bool)
            boxes, cls = boxes[keep], np.array([mapping[int(c)] for c in cls[keep]], dtype=np.int64)
            acc.add(dets, boxes, cls)
            labelled += 1
        progress(0.5 * (n + 1) / len(data.entries))
    metrics = acc.finish()
    if labelled == 0:
        return {"available": False, "note": "n/a (no labels)"}, predictions
    if metrics is None:
        return {"available": False, "note": "n/a (no labelled objects that this model has classes for)"}, predictions
    return {
        "available": True,
        "images": labelled,
        "class_mapping": how,
        "unmapped_classes": unmapped,
        "conf": spec["conf"],
        "iou": spec["iou"],
        **metrics_dict(metrics, model_names, acc),
    }, predictions


def metrics_dict(m: Metrics, names: list[str], acc: Accumulator) -> dict[str, Any]:
    return {
        "map50": m.map50,
        "map50_95": m.map50_95,
        "precision": m.precision,
        "recall": m.recall,
        "f1": m.f1,
        "confidence_at_best_f1": m.confidence_at_best_f1,
        "mean_iou": m.mean_iou,
        "per_class": {names[c]: v for c, v in m.per_class.items()},
        "confusion": {
            "labels": [*names, "background"],
            "matrix": acc.confusion.tolist(),
            "rows": "truth",
            "columns": "prediction",
        },
    }


def speed_pass(runner: Runner, entries: list[Entry], spec: dict[str, Any], progress: Any) -> dict[str, Any]:
    """``repeats`` timed rounds. Each has its own warm-up, then ``iterations`` timed iterations over the cycled
    pictures, and records the wall-clock window it covered so the telemetry of that window can be found afterwards."""
    pictures = [load_rgb(e.path) for e in entries[:CYCLE_PICTURES]]
    warmup, iterations, repeats = int(spec["warmup"]), int(spec["iterations"]), max(1, int(spec.get("repeats") or 1))
    per_repeat = warmup + iterations
    done: list[dict[str, Any]] = []
    for index in range(repeats):
        columns: list[tuple[int, int, int]] = []
        t_start = time.time()
        for i in range(per_repeat):
            if i == warmup:
                t_start = time.time()  # the window is the timed part only
            _, timing = one_picture(
                runner, pictures[i % len(pictures)], spec["imgsz"], spec["conf"], spec["iou"], spec["max_det"]
            )
            if i >= warmup:
                columns.append(timing)
            if i % 5 == 0:
                progress(0.5 + 0.5 * (index * per_repeat + i + 1) / (repeats * per_repeat))
        t_end = time.time()
        pre, inf, post = ([c[k] / NS for c in columns] for k in range(3))
        total = [(a + b + c) / NS for a, b, c in columns]
        done.append(
            {
                "index": index,
                "t_start": t_start,
                "t_end": t_end,
                "stats": stats_ms(total),
                "samples_ms": {"preprocess": pre, "inference": inf, "postprocess": post, "total": total},
            }
        )
    return finalize(
        {
            "warmup": warmup,
            "iterations": iterations,
            "repeats_requested": repeats,
            "pictures_cycled": len(pictures),
            "repeats": done,
        },
        strip=False,
    )


def pin_to_cpus(cpus: list[int] | None) -> list[int] | None:
    """Restrict this process (and so the runtime's threads) to the given logical CPUs. Returns what is now in force, or
    None if no pinning was asked for. A system without CPU affinity (macOS) makes the run 'not available'."""
    if not cpus:
        return None
    import psutil

    process = psutil.Process()
    if not hasattr(process, "cpu_affinity"):
        raise Unavailable("this operating system cannot pin a process to CPUs")
    process.cpu_affinity(sorted(set(cpus)))
    return [int(c) for c in process.cpu_affinity()]


def run(spec: dict[str, Any], progress: Any = lambda _f: None) -> dict[str, Any]:
    data = open_dataset(Path(spec["dataset_dir"]))
    if not data.entries:
        return {"ok": False, "kind": "failed", "error": "The dataset has no pictures."}
    if spec.get("max_images"):
        data.entries = data.entries[: int(spec["max_images"])]
    model_names: list[str] = spec["model_names"]

    pinned = pin_to_cpus(spec.get("cpu_list"))  # before the runtime starts its threads, so they inherit it
    t0 = time.perf_counter_ns()
    runner = load_runner(spec["kind"], Path(spec["model_path"]), int(spec["threads"]))
    load_ms = (time.perf_counter_ns() - t0) / NS
    try:
        blob = to_blob(letterbox(load_rgb(data.entries[0].path), spec["imgsz"])[0])
        t0 = time.perf_counter_ns()
        raw = runner.run(blob)  # the first call is the slow one (lazy initialisation), so it is recorded on its own
        first_ms = (time.perf_counter_ns() - t0) / NS
        if raw.shape[1] - 4 != len(model_names):
            return {
                "ok": False,
                "kind": "failed",
                "error": f"The model outputs {raw.shape[1] - 4} classes but its card lists {len(model_names)} names.",
            }
        accuracy: dict[str, Any]
        predictions: dict[str, list[list[float]]] = {}
        if spec.get("accuracy", True):
            accuracy, predictions = accuracy_pass(runner, data, spec, model_names, progress)
        else:
            accuracy = {"available": False, "note": "not requested"}
        speed = speed_pass(runner, data.entries, spec, progress)
    finally:
        runner.close()
    return {
        "ok": True,
        "runtime": {
            "kind": spec["kind"],
            "threads": spec["threads"],
            "cpus": pinned,
            "versions": package_versions(),
        },
        "load_ms": load_ms,
        "first_inference_ms": first_ms,
        "speed": speed,
        "accuracy": accuracy,
        "predictions": {"min_confidence": PREVIEW_CONF, "pictures": predictions},
        "dataset": {"hash": data.dataset_hash, "images": len(data.entries)},
        "decode": {
            "conf": spec["conf"],
            "iou": spec["iou"],
            "max_det": spec["max_det"],
            "multi_label": True,
        },
    }


def main(argv: list[str]) -> int:
    spec = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    try:
        result = run(spec, lambda f: print(f"PROGRESS {f:.3f}", flush=True))
    except Unavailable as exc:
        result = {"ok": False, "kind": "unavailable", "error": str(exc)}
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        result = {
            "ok": False,
            "kind": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }
    print("RESULT " + json.dumps(result), flush=True)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
