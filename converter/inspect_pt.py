"""Read a checkpoint's model card. Runs in the converter environment, in its own process, after server/edgebench/ptscan.py
accepted the file. Prints one line ``RESULT {json}``.

    python inspect_pt.py path/to/model.pt
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

os.environ.setdefault("YOLO_AUTOINSTALL", "False")  # never let Ultralytics install packages


def main(pt: Path) -> dict[str, object]:
    import ultralytics
    from ultralytics import YOLO

    # The artifact store names files by their hash, with no extension, and Ultralytics decides what a file is from its
    # extension: give it a copy called model.pt.
    with tempfile.TemporaryDirectory(prefix="eb-pt-") as staging:
        staged = Path(staging) / "model.pt"
        shutil.copyfile(pt, staged)
        yolo = YOLO(str(staged))
        model = yolo.model
        names = getattr(model, "names", None) or {}
        ordered = [str(names[i]) for i in sorted(names)] if isinstance(names, dict) else [str(n) for n in names]
        args = getattr(model, "args", None) or {}
        imgsz = args.get("imgsz", 640) if isinstance(args, dict) else getattr(args, "imgsz", 640)
        imgsz = int(imgsz[0] if isinstance(imgsz, (list, tuple)) else imgsz)
        params = sum(p.numel() for p in model.parameters())
        gflops: float | None = None
        try:
            info = yolo.info(verbose=False, imgsz=imgsz)  # (layers, parameters, gradients, GFLOPs) in current Ultralytics
            if isinstance(info, tuple) and len(info) >= 4:
                gflops = round(float(info[3]), 2)
        except Exception:  # GFLOPs is a nicety; the card is still useful without it
            gflops = None
        return {
            "ok": True,
            "task": str(yolo.task),
            "class_names": ordered,
            "imgsz": imgsz,
            "parameters": int(params),
            "gflops": gflops,
            "ultralytics": ultralytics.__version__,
        }


if __name__ == "__main__":
    try:
        print("RESULT " + json.dumps(main(Path(sys.argv[1]))), flush=True)
    except Exception as exc:
        traceback.print_exc()
        message = f"{type(exc).__name__}: {exc}"[:500]
        print("RESULT " + json.dumps({"ok": False, "kind": "failed", "error": message}), flush=True)
        sys.exit(1)
