"""Convert one checkpoint to one runtime format, then check the result against the original PyTorch model.

Runs in the converter environment (torch, ultralytics, onnx, onnxruntime, openvino, ncnn, pnnx; see converter/README.md), in its own
process, started by the server for every conversion. It writes only into ``--out`` and prints one line ``RESULT {json}``.

    python convert.py --op onnx_fp32 --pt model.pt --out workdir --imgsz 640
    python convert.py --op openvino_fp16 --pt model.pt --source workdir_of_onnx_fp32/model.onnx --out workdir2 --imgsz 640

Operations: torchscript, onnx_fp32, onnx_fp16 (needs --source), openvino_fp32 / openvino_fp16 (need --source), ncnn_fp32, ncnn_fp16.
Exit code 0 = converted, 1 = failed, 3 = a needed package is missing (reported, not crashed).
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any

os.environ.setdefault("YOLO_AUTOINSTALL", "False")  # a missing package must be reported, never installed mid-export

# Forward-pass tolerance: largest difference from the PyTorch output, relative to the largest PyTorch value.
TOLERANCE = {"fp32": 1e-3, "fp16": 2e-2}
NEEDS_SOURCE = {"onnx_fp16", "openvino_fp32", "openvino_fp16"}


class Unavailable(Exception):
    """A package or device this operation needs is not there."""


def need(module: str, package: str | None = None) -> Any:
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        raise Unavailable(f"{package or module} is not installed in the converter environment ({exc})") from exc


def sample_blob(imgsz: int) -> Any:
    """A fixed, realistic input: the picture Ultralytics ships with, letterboxed like the runtime does (grey 114 padding)."""
    import numpy as np

    cv2 = need("cv2", "opencv-python")
    ultralytics = need("ultralytics")
    path = Path(ultralytics.__file__).parent / "assets" / "bus.jpg"
    img = cv2.imread(str(path)) if path.exists() else None
    if img is None:
        img = np.random.default_rng(0).integers(0, 255, (480, 640, 3), dtype=np.uint8)
    h, w = img.shape[:2]
    scale = min(imgsz / h, imgsz / w)
    nw, nh = round(w * scale), round(h * scale)
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((imgsz, imgsz, 3), 114, np.uint8)
    top, left = (imgsz - nh) // 2, (imgsz - nw) // 2
    canvas[top : top + nh, left : left + nw] = resized
    return cv2.dnn.blobFromImage(canvas, 1 / 255.0, (imgsz, imgsz), swapRB=True)


def first_output(out: Any) -> Any:
    return out[0] if isinstance(out, (list, tuple)) else out


def torch_reference(pt: Path, blob: Any) -> Any:
    torch = need("torch")
    from ultralytics import YOLO

    model = YOLO(str(pt)).model.float().eval()
    with torch.inference_mode():
        return first_output(model(torch.from_numpy(blob))).cpu().numpy()


# --- operations: each writes its files into `out` and returns the main file's name ---------------------------------------


def ultralytics_export(pt: Path, fmt: str, imgsz: int, **kwargs: Any) -> Path:
    """Export with Ultralytics. ``pt`` is main()'s own staged copy: the export is written next to it, and the whole folder is
    removed when the run ends, so nothing is left behind and the uploaded file is never touched."""
    from ultralytics import YOLO

    return Path(YOLO(str(pt)).export(format=fmt, imgsz=imgsz, **kwargs))


def op_torchscript(pt: Path, out: Path, imgsz: int, **_: Any) -> str:
    shutil.move(str(ultralytics_export(pt, "torchscript", imgsz)), out / "model.torchscript")
    return "model.torchscript"


def op_onnx_fp32(pt: Path, out: Path, imgsz: int, simplify: bool = True, **_: Any) -> str:
    shutil.move(str(ultralytics_export(pt, "onnx", imgsz, simplify=simplify, dynamic=False, half=False)), out / "model.onnx")
    return "model.onnx"


def op_onnx_fp16(source: Path, out: Path, **_: Any) -> str:
    onnx = need("onnx")
    # ONNX Runtime's own converter: onnxconverter-common's output does not load (docs/phase-0-verdict.md).
    convert = need("onnxruntime.transformers.float16", "onnxruntime").convert_float_to_float16
    onnx.save(convert(onnx.load(str(source)), keep_io_types=True), str(out / "model.onnx"))
    return "model.onnx"


def op_openvino(source: Path, out: Path, compress: bool, **_: Any) -> str:
    ov = need("openvino")
    ov.save_model(ov.convert_model(str(source)), str(out / "model.xml"), compress_to_fp16=compress)
    return "model.xml"


def op_ncnn(pt: Path, out: Path, imgsz: int, half: bool, **_: Any) -> str:
    need("ncnn")
    need("pnnx")
    produced = ultralytics_export(pt, "ncnn", imgsz, half=half)
    for name in ("model.ncnn.param", "model.ncnn.bin", "metadata.yaml"):
        if (produced / name).exists():
            shutil.copy2(produced / name, out / name)
    return "model.ncnn.param"


# --- running a converted file, to compare it with PyTorch --------------------------------------------------------------


def run_variant(op: str, main: Path, blob: Any) -> Any:
    import numpy as np

    if op.startswith("onnx"):
        ort = need("onnxruntime")
        sess = ort.InferenceSession(str(main), providers=["CPUExecutionProvider"])
        return sess.run(None, {sess.get_inputs()[0].name: blob})[0]
    if op.startswith("openvino"):
        ov = need("openvino")
        core = ov.Core()
        request = core.compile_model(core.read_model(str(main)), "CPU").create_infer_request()
        request.infer({0: blob})
        return request.get_output_tensor(0).data.copy()
    if op.startswith("ncnn"):
        ncnn = need("ncnn")
        net = ncnn.Net()
        net.opt.use_vulkan_compute = False
        net.load_param(str(main))
        net.load_model(str(main.with_suffix(".bin")))
        source = np.ascontiguousarray(blob[0], dtype=np.float32)  # ncnn.Mat keeps no reference: hold this until clone() is done
        extractor = net.create_extractor()
        extractor.input("in0", ncnn.Mat(source).clone())
        _, result = extractor.extract("out0")
        array = np.array(result)
        return array.reshape(1, *array.shape[-2:]) if array.ndim == 2 else array
    if op == "torchscript":
        torch = need("torch")
        with torch.inference_mode():
            return first_output(torch.jit.load(str(main), map_location="cpu").eval()(torch.from_numpy(blob))).numpy()
    raise ValueError(op)


def verify(op: str, pt: Path, main: Path, imgsz: int) -> dict[str, Any]:
    import numpy as np

    blob = sample_blob(imgsz)
    reference = torch_reference(pt, blob)
    got = np.asarray(run_variant(op, main, blob), dtype=np.float32)
    if got.shape != reference.shape:
        return {"ok": False, "error": f"output shape {got.shape} differs from PyTorch's {reference.shape}"}
    scale = float(np.abs(reference).max()) or 1.0
    diff = float(np.abs(got - reference).max())
    limit = TOLERANCE["fp16" if op.endswith("fp16") else "fp32"]
    return {"ok": diff / scale <= limit, "max_abs_diff": round(diff, 5), "relative": round(diff / scale, 6), "tolerance": limit}


def versions() -> dict[str, str]:
    found = {}
    for package in ("torch", "ultralytics", "onnx", "onnxruntime", "openvino", "ncnn", "numpy"):
        try:
            found[package] = importlib.import_module(package).__version__
        except Exception:
            pass
    return found


PROBE_PACKAGES = ("torch", "ultralytics", "onnx", "onnxruntime", "openvino", "ncnn", "pnnx", "numpy", "opencv-python")


def probe() -> int:
    """List which packages this environment has, without importing them (importing torch takes seconds)."""
    from importlib import metadata

    found: dict[str, str] = {}
    missing: list[str] = []
    for package in PROBE_PACKAGES:
        try:
            found[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            missing.append(package)
    print("RESULT " + json.dumps({"ok": True, "versions": found, "missing": missing, "python": sys.version.split()[0]}), flush=True)
    return 0


def main() -> int:
    if "--probe" in sys.argv:
        return probe()
    ap = argparse.ArgumentParser()
    ap.add_argument("--op", required=True)
    ap.add_argument("--pt", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--source", type=Path, help="the ONNX FP32 file that onnx_fp16 and openvino_* start from")
    ap.add_argument("--no-simplify", action="store_true")
    args = ap.parse_args()

    started = time.perf_counter()
    staging = Path(tempfile.mkdtemp(prefix="eb-pt-"))
    try:
        args.out.mkdir(parents=True, exist_ok=True)
        # The artifact store names files by their hash, with no extension, and Ultralytics decides what a file is from its
        # extension: work from a copy called model.pt.
        pt = staging / "model.pt"
        shutil.copyfile(args.pt, pt)
        if args.op in NEEDS_SOURCE and (args.source is None or not args.source.is_file()):
            raise Unavailable("this variant is built from the ONNX FP32 file, which is not available")
        common = {"pt": pt, "out": args.out, "imgsz": args.imgsz, "source": args.source, "simplify": not args.no_simplify}
        runners = {
            "torchscript": lambda: op_torchscript(**common),
            "onnx_fp32": lambda: op_onnx_fp32(**common),
            "onnx_fp16": lambda: op_onnx_fp16(**common),
            "openvino_fp32": lambda: op_openvino(compress=False, **common),
            "openvino_fp16": lambda: op_openvino(compress=True, **common),
            "ncnn_fp32": lambda: op_ncnn(half=False, **common),
            "ncnn_fp16": lambda: op_ncnn(half=True, **common),
        }
        if args.op not in runners:
            raise ValueError(f"unknown operation {args.op!r}")
        print(f"converting {args.pt.name[:16]} with {args.op}", flush=True)
        main_name = runners[args.op]()
        converted_in = round(time.perf_counter() - started, 2)
        print(f"converted in {converted_in} s; checking against PyTorch", flush=True)
        try:
            check = verify(args.op, pt, args.out / main_name, args.imgsz)
        except Exception as exc:
            # The model converted; a crash in the comparison is a finding about the check, not a reason to throw it away.
            traceback.print_exc()
            check = {"ok": False, "error": f"The check against PyTorch could not run: {type(exc).__name__}: {exc}"[:400]}
        files = sorted(p.name for p in args.out.iterdir() if p.is_file())
        result = {"ok": True, "main": main_name, "files": files, "seconds": converted_in, "verify": check, "versions": versions()}
        print("RESULT " + json.dumps(result), flush=True)
        return 0
    except Unavailable as exc:
        print("RESULT " + json.dumps({"ok": False, "kind": "unavailable", "error": str(exc)}), flush=True)
        return 3
    except Exception as exc:
        traceback.print_exc()
        print("RESULT " + json.dumps({"ok": False, "kind": "failed", "error": f"{type(exc).__name__}: {exc}"[:600]}), flush=True)
        return 1
    finally:
        shutil.rmtree(staging, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
