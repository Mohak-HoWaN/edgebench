"""A stand-in for converter/inspect_pt.py. FAKE_INSPECT=bad makes it report an unreadable model."""

from __future__ import annotations

import json
import os
import re
import sys

if os.environ.get("FAKE_INSPECT") == "bad":
    print("RESULT " + json.dumps({"ok": False, "kind": "failed", "error": "AttributeError: not an Ultralytics model"}))
    raise SystemExit(1)


def trained_with() -> str | None:
    """From a ``TRAINED_WITH=8.4.208`` marker inside the file (a browser test), else FAKE_TRAINED_WITH."""
    with open(sys.argv[1], "rb") as f:
        marked = re.search(rb"TRAINED_WITH=([0-9.]+)", f.read())
    return marked.group(1).decode() if marked else (os.environ.get("FAKE_TRAINED_WITH") or None)


card = {
    "ok": True,
    "task": "detect",
    "class_names": ["chips", "biscuit", "chocolate"],
    "imgsz": 640,
    "parameters": 2616248,
    "gflops": 6.5,
    # FAKE_TRAINED_WITH / FAKE_TRAIN_MODEL stand for the library and architecture the checkpoint says it came from
    "trained_with": trained_with(),
    "train_model": os.environ.get("FAKE_TRAIN_MODEL") or None,
}
print("RESULT " + json.dumps(card))
