"""Where a run goes wrong: the pictures with a missed object, a wrongly named object or a made-up one, worst first.

The rules are those of the confusion matrix (a detection counts from confidence 0.25, and matches a real box that it
overlaps by more than 0.45), with classes compared by name, so this list agrees with the numbers on the run page. Pure
functions over the stored detections and the dataset's boxes; ``export`` writes a folder-shaped zip for the next round
of annotation.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Any

CONF = 0.25
IOU = 0.45
WEIGHT = {"wrong": 3, "missed": 2, "invented": 1}  # a wrong name costs more than a miss, a miss more than a false alarm


def _iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


@lru_cache(maxsize=8)
def predictions(path: str) -> dict[str, Any]:
    """A run's stored detections: ``{"pictures": {"3": [[x1, y1, x2, y2, score, class], ...]}}``, relative boxes."""
    data: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    return data


def one_picture(
    labels: list[list[float]], dataset_names: list[str], found: list[list[float]], model_names: list[str]
) -> dict[str, Any]:
    """Compare one picture's real boxes with what the model found. Boxes in, issues and a severity out."""
    truth: list[dict[str, Any]] = [
        {"name": dataset_names[int(c)], "box": [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]}
        for c, cx, cy, w, h in labels
        if int(c) < len(dataset_names)
        and dataset_names[int(c)] in model_names  # a class the model lacks is left out, as in the score
    ]
    seen: list[dict[str, Any]] = [
        {"name": model_names[int(c)], "box": [x1, y1, x2, y2], "score": float(score)}
        for x1, y1, x2, y2, score, c in found
        if score >= CONF and int(c) < len(model_names)
    ]
    pairs = sorted(
        ((_iou(t["box"], f["box"]), ti, fi) for ti, t in enumerate(truth) for fi, f in enumerate(seen)), reverse=True
    )
    used_t: set[int] = set()
    used_f: set[int] = set()
    issues: list[dict[str, Any]] = []
    for overlap, ti, fi in pairs:
        if overlap <= IOU or ti in used_t or fi in used_f:
            continue
        used_t.add(ti)
        used_f.add(fi)
        if truth[ti]["name"] != seen[fi]["name"]:
            issues.append(
                {
                    "kind": "wrong",
                    "truth": truth[ti]["name"],
                    "answer": seen[fi]["name"],
                    "score": seen[fi]["score"],
                    "box": truth[ti]["box"],
                }
            )
    for ti, t in enumerate(truth):
        if ti not in used_t:
            issues.append({"kind": "missed", "truth": t["name"], "box": t["box"]})
    for fi, f in enumerate(seen):
        if fi not in used_f:
            issues.append({"kind": "invented", "answer": f["name"], "score": f["score"], "box": f["box"]})
    return {"issues": issues, "severity": sum(WEIGHT[i["kind"]] for i in issues), "truth": truth, "found": seen}


def analyse(
    images: list[dict[str, Any]],
    dataset_names: list[str],
    pictures: dict[str, list[list[float]]],
    model_names: list[str],
    limit: int = 100,
) -> dict[str, Any]:
    """Every annotated picture the run saw, the ones with a problem worst first (ties: the earlier picture)."""
    checked = 0
    bad: list[dict[str, Any]] = []
    totals = {"missed": 0, "wrong": 0, "invented": 0}
    for index, im in enumerate(images):
        if im["labels"] is None or str(index) not in pictures:
            continue
        checked += 1
        result = one_picture(im["labels"], dataset_names, pictures[str(index)], model_names)
        if not result["issues"]:
            continue
        for issue in result["issues"]:
            totals[issue["kind"]] += 1
        bad.append(
            {
                "index": index,
                "original": im["original"],
                "width": im["width"],
                "height": im["height"],
                "source": im["source"],
                **result,
            }
        )
    bad.sort(key=lambda p: (-p["severity"], p["index"]))
    return {"checked": checked, "with_problems": len(bad), "totals": totals, "pictures": bad[:limit]}


def _yolo(boxes: list[dict[str, Any]], names: list[str]) -> str:
    """YOLO label lines (class, centre x and y, width, height, all relative); a class not in ``names`` is skipped."""
    lines = []
    for b in boxes:
        if b["name"] in names:
            x1, y1, x2, y2 = b["box"]
            lines.append(
                f"{names.index(b['name'])} {(x1 + x2) / 2:.6f} {(y1 + y2) / 2:.6f} {x2 - x1:.6f} {y2 - y1:.6f}"
            )
    return "\n".join(lines) + ("\n" if lines else "")


def export(dataset_zip: Path, picked: list[dict[str, Any]], dataset_names: list[str]) -> bytes:
    """The chosen pictures as a folder for the next annotation round: the pictures, the real labels, what the model
    found (as starting labels to correct), the dataset's class list, and a ``why.csv`` for what went wrong."""
    out = io.BytesIO()
    why = io.StringIO()
    writer = csv.writer(why)
    writer.writerow(["picture", "missed", "wrong class", "made up", "what"])
    with zipfile.ZipFile(dataset_zip) as source, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        manifest = json.loads(source.read("data.json"))
        for p in picked:
            im = manifest["images"][p["index"]]
            stem = Path(p["original"]).stem
            z.writestr(f"images/{p['original']}", source.read(im["file"]))
            z.writestr(f"labels_real/{stem}.txt", _yolo(p["truth"], dataset_names))
            z.writestr(f"labels_from_the_model/{stem}.txt", _yolo(p["found"], dataset_names))
            kinds = [i["kind"] for i in p["issues"]]
            what = "; ".join(
                f"missed {i['truth']}"
                if i["kind"] == "missed"
                else f"{i['truth']} named as {i['answer']}"
                if i["kind"] == "wrong"
                else f"made up {i['answer']}"
                for i in p["issues"]
            )
            writer.writerow([p["original"], kinds.count("missed"), kinds.count("wrong"), kinds.count("invented"), what])
        z.writestr("classes.txt", "\n".join(dataset_names) + "\n")
        z.writestr("why.csv", why.getvalue())
    return out.getvalue()
