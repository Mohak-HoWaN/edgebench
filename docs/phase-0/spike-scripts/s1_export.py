"""Phase 0 spike 1: try every conversion in the planned matrix, independently, and record what happens.

Run from spikes/ with the spikes venv:  .venv\\Scripts\\python scripts\\s1_export.py [step ...]
Writes out/s1_results.json after every step so a crash keeps earlier results.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
import traceback
from pathlib import Path

import cv2
import numpy as np

SP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SP.parent.parent / "project" / "pipeline"))
from jonaru.detector import letterbox  # noqa: E402  (same preprocessing the runtime uses)

OUT = SP / "out"
WORK = SP / "models"
PT = WORK / "yolo11n.pt"
IMGS = sorted((SP / "data" / "coco128" / "images" / "train2017").glob("*.jpg"))
RESULTS = OUT / "s1_results.json"
results: dict[str, dict] = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}


def blob(path: Path) -> np.ndarray:
    img = cv2.imread(str(path))
    padded, *_ = letterbox(img, 640)
    return cv2.dnn.blobFromImage(padded, 1 / 255.0, (640, 640), swapRB=True)


def size_mb(p: Path) -> float:
    if p.is_dir():
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / 1e6
    return p.stat().st_size / 1e6


def step(name: str, fn) -> None:
    t0 = time.perf_counter()
    try:
        out = Path(fn())
        results[name] = {"ok": True, "seconds": round(time.perf_counter() - t0, 1),
                         "size_mb": round(size_mb(out), 2), "path": str(out.relative_to(SP))}
    except BaseException as exc:  # noqa: BLE001 - a spike records every failure, including SystemExit
        results[name] = {"ok": False, "seconds": round(time.perf_counter() - t0, 1),
                         "error": f"{type(exc).__name__}: {str(exc)[:400]}",
                         "trace_tail": traceback.format_exc().splitlines()[-4:]}
    RESULTS.write_text(json.dumps(results, indent=2))
    r = results[name]
    print(f"[{name}] ok={r['ok']} {r['seconds']}s " + (f"{r['size_mb']} MB" if r["ok"] else r["error"]), flush=True)


def ultralytics_export(fmt: str, **kw) -> Path:
    from ultralytics import YOLO

    scratch = OUT / f"scratch_{fmt}"
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    copy = scratch / PT.name
    shutil.copy2(PT, copy)
    return Path(YOLO(str(copy)).export(format=fmt, imgsz=640, **kw))


def onnx_fp32() -> Path:
    produced = ultralytics_export("onnx", simplify=True, dynamic=False, half=False)
    dest = WORK / "yolo11n_fp32.onnx"
    shutil.copy2(produced, dest)
    return dest


def torchscript() -> Path:
    dest = WORK / "yolo11n.torchscript"
    shutil.copy2(ultralytics_export("torchscript"), dest)
    return dest


def onnx_fp16() -> Path:
    import onnx
    from onnxconverter_common import float16

    model = float16.convert_float_to_float16(onnx.load(str(WORK / "yolo11n_fp32.onnx")), keep_io_types=True)
    dest = WORK / "yolo11n_fp16.onnx"
    onnx.save(model, str(dest))
    return dest


def ov_fp(compress: bool) -> Path:
    import openvino as ov

    dest = WORK / ("yolo11n_ov_fp16.xml" if compress else "yolo11n_ov_fp32.xml")
    ov.save_model(ov.convert_model(str(WORK / "yolo11n_fp32.onnx")), str(dest), compress_to_fp16=compress)
    return dest


def ov_int8(images: list[Path], tag: str) -> Path:
    import nncf
    import openvino as ov

    dataset = nncf.Dataset([blob(p) for p in images])
    quantized = nncf.quantize(ov.Core().read_model(str(WORK / "yolo11n_ov_fp32.xml")), dataset)
    dest = WORK / f"yolo11n_ov_int8_{tag}.xml"
    ov.save_model(quantized, str(dest))
    return dest


def onnx_int8_dynamic() -> Path:
    from onnxruntime.quantization import QuantType, quantize_dynamic

    dest = WORK / "yolo11n_int8_dynamic.onnx"
    quantize_dynamic(str(WORK / "yolo11n_fp32.onnx"), str(dest), weight_type=QuantType.QInt8)
    return dest


def onnx_int8_static() -> Path:
    from onnxruntime.quantization import CalibrationDataReader, QuantFormat, QuantType, quantize_static

    class Reader(CalibrationDataReader):
        def __init__(self) -> None:
            self.it = iter(blob(p) for p in IMGS)

        def get_next(self):
            b = next(self.it, None)
            return None if b is None else {"images": b}

    dest = WORK / "yolo11n_int8_static_qdq.onnx"
    quantize_static(str(WORK / "yolo11n_fp32.onnx"), str(dest), Reader(), quant_format=QuantFormat.QDQ,
                    activation_type=QuantType.QUInt8, weight_type=QuantType.QInt8)
    return dest


def onnx_fp16_blockresize() -> Path:
    import onnx
    from onnxconverter_common import float16

    block = list(float16.DEFAULT_OP_BLOCK_LIST) + ["Resize"]
    model = float16.convert_float_to_float16(onnx.load(str(WORK / "yolo11n_fp32.onnx")), keep_io_types=True,
                                             op_block_list=block)
    dest = WORK / "yolo11n_fp16_blockresize.onnx"
    onnx.save(model, str(dest))
    return dest


def onnx_fp16_ortconv() -> Path:
    import onnx
    from onnxruntime.transformers.float16 import convert_float_to_float16

    model = convert_float_to_float16(onnx.load(str(WORK / "yolo11n_fp32.onnx")), keep_io_types=True)
    dest = WORK / "yolo11n_fp16_ortconv.onnx"
    onnx.save(model, str(dest))
    return dest


def onnx_int8_static_nohead() -> Path:
    import onnx
    from onnxruntime.quantization import CalibrationDataReader, QuantFormat, QuantType, quantize_static

    names = [n.name for n in onnx.load(str(WORK / "yolo11n_fp32.onnx")).graph.node if n.name.startswith("/model.23/")]
    assert names, "detect head prefix /model.23/ not found"

    class Reader(CalibrationDataReader):
        def __init__(self) -> None:
            self.it = iter(blob(p) for p in IMGS)

        def get_next(self):
            b = next(self.it, None)
            return None if b is None else {"images": b}

    dest = WORK / "yolo11n_int8_static_nohead.onnx"
    quantize_static(str(WORK / "yolo11n_fp32.onnx"), str(dest), Reader(), quant_format=QuantFormat.QDQ,
                    activation_type=QuantType.QUInt8, weight_type=QuantType.QInt8, nodes_to_exclude=names)
    print(f"excluded {len(names)} head nodes", flush=True)
    return dest


def trt_engine(int8: bool) -> Path:
    from ultralytics import YOLO

    yaml_path = SP / "data" / "coco128.yaml"
    names = YOLO(str(PT)).names
    lines = [f"path: {(SP / 'data' / 'coco128').as_posix()}", "train: images/train2017", "val: images/train2017", "names:"]
    yaml_path.write_text("\n".join(lines + [f"  {k}: {v}" for k, v in names.items()]) + "\n")
    kw = {"int8": True, "data": str(yaml_path), "batch": 1} if int8 else {"half": True}
    produced = ultralytics_export("engine", device=0, workspace=2, **kw)
    dest = WORK / ("yolo11n_trt_int8.engine" if int8 else "yolo11n_trt_fp16.engine")
    shutil.copy2(produced, dest)
    return dest


def ncnn_export(half: bool) -> Path:
    produced = ultralytics_export("ncnn", half=half)
    dest = WORK / ("yolo11n_ncnn_fp16" if half else "yolo11n_ncnn_fp32")
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(produced, dest)
    return dest


STEPS = {
    "onnx_fp32": onnx_fp32,
    "torchscript": torchscript,
    "onnx_fp16": onnx_fp16,
    "ov_fp32": lambda: ov_fp(False),
    "ov_fp16": lambda: ov_fp(True),
    "ov_int8_calib128": lambda: ov_int8(IMGS, "calib128"),
    "ov_int8_calib1x10": lambda: ov_int8([IMGS[0]] * 10, "calib1x10"),
    "onnx_int8_dynamic": onnx_int8_dynamic,
    "onnx_int8_static_qdq": onnx_int8_static,
    "onnx_fp16_blockresize": onnx_fp16_blockresize,
    "onnx_fp16_ortconv": onnx_fp16_ortconv,
    "onnx_int8_static_nohead": onnx_int8_static_nohead,
    "trt_fp16": lambda: trt_engine(False),
    "trt_int8": lambda: trt_engine(True),
    "ncnn_fp32": lambda: ncnn_export(False),
    "ncnn_fp16": lambda: ncnn_export(True),
}

if __name__ == "__main__":
    assert PT.is_file() and len(IMGS) == 128, "stage models/yolo11n.pt and data/coco128 first"
    wanted = sys.argv[1:] or list(STEPS)
    for name in wanted:
        step(name, STEPS[name])
