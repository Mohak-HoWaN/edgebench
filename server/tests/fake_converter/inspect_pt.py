"""A stand-in for converter/inspect_pt.py. FAKE_INSPECT=bad makes it report an unreadable model."""

from __future__ import annotations

import json
import os

if os.environ.get("FAKE_INSPECT") == "bad":
    print("RESULT " + json.dumps({"ok": False, "kind": "failed", "error": "AttributeError: not an Ultralytics model"}))
    raise SystemExit(1)
card = {
    "ok": True,
    "task": "detect",
    "class_names": ["chips", "biscuit", "chocolate"],
    "imgsz": 640,
    "parameters": 2616248,
    "gflops": 6.5,
}
print("RESULT " + json.dumps(card))
