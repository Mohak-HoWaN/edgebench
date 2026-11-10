"""A stand-in for edgebench_agent.bench with the same protocol, steered by FAKE_BENCH (ok, crash, unavailable, slow)."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
behaviour = os.environ.get("FAKE_BENCH", "ok")
if pids := os.environ.get("FAKE_BENCH_PIDS"):
    with open(pids, "a", encoding="utf-8") as f:
        f.write(f"{os.getpid()}\n")
print("PROGRESS 0.250", flush=True)
if behaviour == "slow":
    time.sleep(60)
if behaviour == "crash":
    print("about to crash", flush=True)
    os._exit(7)  # no RESULT line, like a native crash
if behaviour == "unavailable":
    print("RESULT " + json.dumps({"ok": False, "kind": "unavailable", "error": "ncnn is not installed on this device"}))
    sys.exit(1)
assert Path(spec["model_path"]).exists() and (Path(spec["dataset_dir"]) / "data.json").exists()
print("PROGRESS 1.000", flush=True)
print(
    "RESULT "
    + json.dumps(
        {
            "ok": True,
            "runtime": {"kind": spec["kind"], "threads": spec["threads"]},
            "speed": {"stages": {"total": {"p50": 9.5}}},
            "accuracy": {"available": False, "note": "fake"},
        }
    ),
    flush=True,
)
