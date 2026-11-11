"""A stand-in for converter/convert.py used by the server tests: same command line, same RESULT protocol, no torch.

FAKE_BEHAVIOR is a comma list like ``ncnn_fp16=fail,torchscript=hang``; behaviours: fail, unavailable, hang, mismatch.
FAKE_LOG, if set, gets one line per conversion that really ran (so tests can tell a cache hit from a run).
FAKE_PIDS, if set, gets the process id of every run (so tests can check that a cancelled run was killed).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

behaviors = dict(item.split("=", 1) for item in os.environ.get("FAKE_BEHAVIOR", "").split(",") if "=" in item)

if "--probe" in sys.argv:
    print(
        "RESULT "
        + json.dumps({"ok": True, "versions": {"torch": "0", "ultralytics": "0"}, "missing": ["ncnn"], "python": "3"})
    )
    sys.exit(0)

ap = argparse.ArgumentParser()
ap.add_argument("--op", required=True)
ap.add_argument("--pt", required=True)
ap.add_argument("--out", required=True, type=Path)
ap.add_argument("--imgsz", type=int, default=640)
ap.add_argument("--source", type=Path)
ap.add_argument("--no-simplify", action="store_true")
ap.add_argument("--calibration", type=Path)
args = ap.parse_args()

if log := os.environ.get("FAKE_LOG"):
    with open(log, "a", encoding="utf-8") as f:
        f.write(args.op + "\n")
if pids := os.environ.get("FAKE_PIDS"):
    with open(pids, "a", encoding="utf-8") as f:
        f.write(f"{args.op} {os.getpid()}\n")

behavior = behaviors.get(args.op)
needs_source = args.op in ("onnx_fp16", "openvino_fp32", "openvino_fp16", "openvino_int8", "onnx_int8")
pictures = sorted(p.name for p in args.calibration.iterdir()) if args.calibration and args.calibration.is_dir() else []
if args.op.endswith("int8") and len(pictures) < 50:  # the real converter refuses the same way
    print(
        "RESULT "
        + json.dumps(
            {
                "ok": False,
                "kind": "failed",
                "error": f"calibration needs at least 50 readable pictures and was given {len(pictures)}",
            }
        )
    )
    sys.exit(1)
print(f"fake converting {args.op}", flush=True)

if behavior == "hang":
    time.sleep(300)
if behavior == "unavailable" or (needs_source and (args.source is None or not args.source.is_file())):
    print(
        "RESULT "
        + json.dumps({"ok": False, "kind": "unavailable", "error": f"{args.op}: a needed package is not installed"})
    )
    sys.exit(3)
if behavior == "fail":
    print("Traceback (most recent call last):\n  ...\nRuntimeError: boom", file=sys.stderr, flush=True)
    print("RESULT " + json.dumps({"ok": False, "kind": "failed", "error": "RuntimeError: boom"}))
    sys.exit(1)

args.out.mkdir(parents=True, exist_ok=True)
main = {
    "onnx_fp32": "model.onnx",
    "onnx_fp16": "model.onnx",
    "torchscript": "model.torchscript",
    "openvino_fp32": "model.xml",
    "openvino_fp16": "model.xml",
    "ncnn_fp32": "model.ncnn.param",
    "ncnn_fp16": "model.ncnn.param",
    "openvino_int8": "model.xml",
    "onnx_int8": "model.onnx",
}[args.op]
(args.out / main).write_text(f"fake {args.op} of {Path(args.pt).name}")
if pictures:  # lets a test see exactly which pictures the converter was given
    (args.out / "calibration.txt").write_text("\n".join(pictures))
if main.endswith(".xml"):  # bundles keep their weights in a second file
    (args.out / "model.bin").write_bytes(b"w" * 1000)
elif main.endswith(".param"):
    (args.out / "model.ncnn.bin").write_bytes(b"w" * 1000)
files = sorted(p.name for p in args.out.iterdir())
ok = behavior != "mismatch"
error = "RuntimeError: the check crashed" if behavior == "verifyfail" else None
verify: dict[str, Any] = {
    "ok": ok,
    "max_abs_diff": 0.5 if not ok else 0.0,
    "relative": 0.9 if not ok else 0.0,
    "tolerance": 0.001,
}
if error:
    verify = {"ok": False, "error": error}
print(
    "RESULT "
    + json.dumps({"ok": True, "main": main, "files": files, "seconds": 0.01, "verify": verify, "versions": {}}),
    flush=True,
)
