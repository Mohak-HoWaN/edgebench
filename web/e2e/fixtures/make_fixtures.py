"""Regenerate the upload fixtures used by e2e/models.spec.ts (run from the repository root with the server's Python).

    .venv\\Scripts\\python web\\e2e\\fixtures\\make_fixtures.py

``checkpoint.fixture`` is what the server's checkpoint scanner accepts: a zip holding a pickle that uses only allowed names.
``evil.fixture`` is the same with one extra object whose pickle would call os.system; the scanner must refuse it.
Neither contains a model; the stand-in converter the e2e server uses does not read them. Names avoid .pt/.bin, which are git-ignored.
``shelf.fixture`` is a small YOLO dataset zip (six pictures from two capture sources, two classes) and ``notes.fixture`` is a zip
with no pictures in it, which the importer must refuse.
"""

from __future__ import annotations

import io
import os
import pickle
import zipfile
from collections import OrderedDict
from pathlib import Path
from typing import Any

from PIL import Image

HERE = Path(__file__).parent


class Evil:
    def __reduce__(self) -> tuple[Any, tuple[Any, ...]]:
        return os.system, ("echo pwned",)


def checkpoint(extra: Any = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        entry = zipfile.ZipInfo("model/data.pkl", date_time=(2026, 1, 1, 0, 0, 0))  # fixed time: same bytes every run
        z.writestr(entry, pickle.dumps(OrderedDict(model=OrderedDict(), extra=extra), protocol=2))
    return buf.getvalue()


def dataset() -> bytes:
    """Six 80 x 60 pictures, three per capture source, each with one box; labels in YOLO format."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:

        def add(name: str, data: bytes) -> None:
            z.writestr(zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)), data)

        add("data.yaml", b"names:\n  0: chips\n  1: biscuit\n")
        for i in range(6):
            source = "rpi-cam3-wide" if i < 3 else "mobile"
            jpeg = io.BytesIO()
            Image.new("RGB", (80, 60), (40 * i + 10, 120, 200 - 30 * i)).save(jpeg, "JPEG", quality=90)
            add(f"images/{source}/{i}.jpg", jpeg.getvalue())
            add(f"labels/{source}/{i}.txt", f"{i % 2} 0.5 0.5 0.4 0.5\n".encode())
    return buf.getvalue()


def folder() -> None:
    """The same six pictures as ``shelf.fixture`` as a real folder (for choosing a folder or loose photos in the browser)."""
    import shutil

    root = HERE / "shelf-folder"
    shutil.rmtree(root, ignore_errors=True)
    (root).mkdir()
    (root / "data.yaml").write_bytes(b"names:\n  0: chips\n  1: biscuit\n")
    for i in range(6):
        source = "rpi-cam3-wide" if i < 3 else "mobile"
        for sub in ("images", "labels"):
            (root / sub / source).mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (80, 60), (40 * i + 10, 120, 200 - 30 * i)).save(root / "images" / source / f"{i}.jpg", "JPEG", quality=90)
        (root / "labels" / source / f"{i}.txt").write_bytes(f"{i % 2} 0.5 0.5 0.4 0.5\n".encode())


def text_only_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(zipfile.ZipInfo("notes.txt", date_time=(2026, 1, 1, 0, 0, 0)), b"no pictures here")
    return buf.getvalue()


if __name__ == "__main__":
    (HERE / "shelf.fixture").write_bytes(dataset())
    (HERE / "notes.fixture").write_bytes(text_only_zip())
    folder()
    (HERE / "checkpoint.fixture").write_bytes(checkpoint())
    (HERE / "evil.fixture").write_bytes(checkpoint(Evil()))
    print("written:", sorted(p.name for p in HERE.glob("*.fixture")))
