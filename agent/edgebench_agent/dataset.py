"""Read the normalised dataset zip the server builds (``data.json`` + ``images/*.jpg``) from a local cache folder."""

from __future__ import annotations

import json
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


@dataclass
class Entry:
    path: Path
    original: str
    width: int
    height: int
    source: str
    labels: NDArray[np.float64] | None  # (n, 5): class, centre x, centre y, width, height, all relative to the image


@dataclass
class Dataset:
    names: list[str]
    entries: list[Entry]
    dataset_hash: str


def unpack(zip_path: Path, dest: Path) -> Path:
    """Unpack once; a finished unpack is marked, so a second call (or a second run) costs nothing."""
    done = dest / ".complete"
    if done.exists():
        return dest
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    root = dest.resolve()
    with zipfile.ZipFile(zip_path) as z:
        for member in z.infolist():
            target = (root / member.filename).resolve()
            if root not in target.parents and target != root:
                raise ValueError(f"unsafe path in dataset zip: {member.filename!r}")
        z.extractall(dest)
    done.write_text("ok")
    return dest


def open_dataset(folder: Path) -> Dataset:
    data = json.loads((folder / "data.json").read_text(encoding="utf-8"))
    entries = [
        Entry(
            path=folder / im["file"],
            original=im["original"],
            width=im["width"],
            height=im["height"],
            source=im["source"],
            labels=None if im["labels"] is None else np.asarray(im["labels"], dtype=np.float64).reshape(-1, 5),
        )
        for im in data["images"]
    ]
    return Dataset(names=list(data["names"]), entries=entries, dataset_hash=data["dataset_hash"])


def load_rgb(path: Path) -> NDArray[np.uint8]:
    if cv2 is not None:
        bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError(f"cannot read picture {path.name}")
        return np.ascontiguousarray(bgr[:, :, ::-1])
    from PIL import Image

    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"))


def truth_boxes(entry: Entry) -> tuple[NDArray[np.float64], NDArray[np.int64]]:
    """Ground truth in pixels: boxes ``(n, 4)`` as x1 y1 x2 y2 and classes ``(n,)``."""
    assert entry.labels is not None
    lab = entry.labels
    w, h = entry.width, entry.height
    boxes = np.stack(
        [
            (lab[:, 1] - lab[:, 3] / 2) * w,
            (lab[:, 2] - lab[:, 4] / 2) * h,
            (lab[:, 1] + lab[:, 3] / 2) * w,
            (lab[:, 2] + lab[:, 4] / 2) * h,
        ],
        axis=1,
    )
    return boxes, lab[:, 0].astype(np.int64)
