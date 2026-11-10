"""Phase 0 spike 2: latency per runtime/precision/thread count, and detection drift against the FP32 ONNX reference.

Run from spikes/:  .venv\\Scripts\\python scripts\\s2_bench.py
Reads out/s1_results.json (only variants that converted are measured). Writes out/s2_results.json.
Latency is the runtime call only (preprocessed tensor in, raw tensor out), 10 warm-up + 100 timed runs.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

import cv2
import numpy as np

SP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SP.parent.parent / "project" / "pipeline"))
from jonaru.detector import decode, letterbox  # noqa: E402

IMGS = sorted((SP / "data" / "coco128" / "images" / "train2017").glob("*.jpg"))
S1 = json.loads((SP / "out" / "s1_results.json").read_text())
THREADS = (1, 4, 8)
DRIFT_IMAGES = 20
REFERENCE = "onnx_fp32"


def prep(path: Path):
    img = cv2.imread(str(path))
    h, w = img.shape[:2]
    padded, scale, px, py = letterbox(img, 640)
    return cv2.dnn.blobFromImage(padded, 1 / 255.0, (640, 640), swapRB=True), (scale, px, py, w, h)


def make_runner(kind: str, path: Path, threads: int):
    if kind == "ort":
        import onnxruntime as ort

        so = ort.SessionOptions()
        so.intra_op_num_threads, so.inter_op_num_threads = threads, 1
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        sess = ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])
        name = sess.get_inputs()[0].name
        return lambda b: sess.run(None, {name: b})[0]
    if kind == "ov":
        import openvino as ov

        core = ov.Core()
        comp = core.compile_model(core.read_model(str(path)), "CPU",
                                  {"PERFORMANCE_HINT": "LATENCY", "INFERENCE_NUM_THREADS": threads})
        req = comp.create_infer_request()

        def run(b):
            req.infer({0: b})
            return req.get_output_tensor(0).data.copy()

        return run
    if kind == "ncnn":
        import ncnn

        net = ncnn.Net()
        net.opt.num_threads, net.opt.use_vulkan_compute = threads, False
        net.load_param(str(next(path.glob("*.param"))))
        net.load_model(str(next(path.glob("*.bin"))))

        def run(b):
            ex = net.create_extractor()
            src = np.ascontiguousarray(b[0], dtype=np.float32)  # must stay alive until clone(): ncnn.Mat keeps no reference to it
            ex.input("in0", ncnn.Mat(src).clone())
            _, out = ex.extract("out0")
            arr = np.array(out)
            return arr.reshape(1, *arr.shape[-2:])

        return run
    if kind == "trt":
        import tensorrt as trt
        import torch

        with open(path, "rb") as f:  # Ultralytics prepends a length-prefixed JSON header to the engine bytes
            f.read(int.from_bytes(f.read(4), "little"))
            engine = trt.Runtime(trt.Logger(trt.Logger.WARNING)).deserialize_cuda_engine(f.read())
        ctx = engine.create_execution_context()
        n_in, n_out = engine.get_tensor_name(0), engine.get_tensor_name(1)
        tdt = lambda name: torch.from_numpy(np.empty(0, dtype=trt.nptype(engine.get_tensor_dtype(name)))).dtype  # noqa: E731
        inp = torch.empty(tuple(engine.get_tensor_shape(n_in)), device="cuda", dtype=tdt(n_in))
        out = torch.empty(tuple(engine.get_tensor_shape(n_out)), device="cuda", dtype=tdt(n_out))
        ctx.set_tensor_address(n_in, inp.data_ptr())
        ctx.set_tensor_address(n_out, out.data_ptr())
        stream = torch.cuda.Stream()

        def run(b):
            with torch.cuda.stream(stream):
                inp.copy_(torch.from_numpy(b))
                ctx.execute_async_v3(stream.cuda_stream)
            stream.synchronize()
            return out.float().cpu().numpy()

        return run
    if kind in ("ts_cpu", "ts_cuda"):
        import torch

        torch.set_num_threads(threads)
        dev = "cuda" if kind == "ts_cuda" else "cpu"
        model = torch.jit.load(str(path), map_location=dev).eval()

        def run(b):
            with torch.inference_mode():
                out = model(torch.from_numpy(b).to(dev))
                out = out[0] if isinstance(out, (tuple, list)) else out
                return out.cpu().numpy()

        return run
    raise ValueError(kind)


def iou(a: np.ndarray, b: np.ndarray) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def compare(ref: np.ndarray, var: np.ndarray) -> tuple[int, float]:
    """Greedy same-class IoU>=0.5 matches, highest reference score first. Returns (matches, summed |score diff|)."""
    used, matches, diff = set(), 0, 0.0
    for r in ref[np.argsort(-ref[:, 4])] if len(ref) else []:
        best, best_i = 0.5, -1
        for i, v in enumerate(var):
            if i not in used and int(v[5]) == int(r[5]) and (o := iou(r, v)) >= best:
                best, best_i = o, i
        if best_i >= 0:
            used.add(best_i)
            matches += 1
            diff += abs(float(r[4]) - float(var[best_i][4]))
    return matches, diff


def latency(run, b) -> dict:
    for _ in range(10):
        run(b)
    t = []
    for _ in range(100):
        t0 = time.perf_counter_ns()
        run(b)
        t.append((time.perf_counter_ns() - t0) / 1e6)
    t = np.array(t)
    return {"mean_ms": round(float(t.mean()), 2), "p50_ms": round(float(np.percentile(t, 50)), 2),
            "p95_ms": round(float(np.percentile(t, 95)), 2), "std_ms": round(float(t.std()), 2)}


def candidates() -> dict[str, tuple[str, Path]]:
    c = {
        "onnx_fp32": ("ort", "onnx_fp32"), "onnx_fp16": ("ort", "onnx_fp16"),
        "onnx_int8_dynamic": ("ort", "onnx_int8_dynamic"), "onnx_int8_static_qdq": ("ort", "onnx_int8_static_qdq"),
        "onnx_fp16_blockresize": ("ort", "onnx_fp16_blockresize"), "onnx_fp16_ortconv": ("ort", "onnx_fp16_ortconv"),
        "onnx_int8_static_nohead": ("ort", "onnx_int8_static_nohead"),
        "ov_fp32": ("ov", "ov_fp32"), "ov_fp16": ("ov", "ov_fp16"),
        "ov_int8_calib128": ("ov", "ov_int8_calib128"), "ov_int8_calib1x10": ("ov", "ov_int8_calib1x10"),
        "ncnn_fp32": ("ncnn", "ncnn_fp32"), "ncnn_fp16": ("ncnn", "ncnn_fp16"),
        "trt_fp16": ("trt", "trt_fp16"), "trt_int8": ("trt", "trt_int8"),
        "torchscript_cpu": ("ts_cpu", "torchscript"), "torchscript_cuda": ("ts_cuda", "torchscript"),
    }
    return {n: (k, SP / S1[src]["path"]) for n, (k, src) in c.items() if S1.get(src, {}).get("ok")}


def main() -> None:
    cands = candidates()
    print("measuring:", ", ".join(cands), flush=True)
    sample, _ = prep(IMGS[0])
    drift_inputs = [prep(p) for p in IMGS[:DRIFT_IMAGES]]
    ref_run = make_runner(*cands[REFERENCE], 4)
    ref_dets = [decode(ref_run(b), *g[:3], g[3], g[4], 0.25, 0.5) for b, g in drift_inputs]
    ref_raw = [ref_run(b) for b, _ in drift_inputs[:5]]
    out_file = SP / "out" / "s2_results.json"
    results: dict[str, dict] = json.loads(out_file.read_text()) if out_file.exists() else {}
    wanted = sys.argv[1:] or list(cands)
    for name, (kind, path) in ((n, cands[n]) for n in wanted if n in cands):
        res: dict = {"latency": {}}
        try:
            for th in ((1,) if kind in ("ts_cuda", "trt") else THREADS):
                res["latency"][f"threads_{th}"] = latency(make_runner(kind, path, th), sample)
            run = make_runner(kind, path, 4)
            dets = [decode(run(b), *g[:3], g[3], g[4], 0.25, 0.5) for b, g in drift_inputs]
            n_ref, n_var = sum(len(d) for d in ref_dets), sum(len(d) for d in dets)
            m = [compare(r, v) for r, v in zip(ref_dets, dets)]
            matched, sdiff = sum(x[0] for x in m), sum(x[1] for x in m)
            raw_diff = [float(np.abs(ref_raw[i][0, 4:] - run(drift_inputs[i][0])[0, 4:]).max()) for i in range(5)]
            res["drift"] = {"ref_boxes": n_ref, "variant_boxes": n_var, "matched": matched,
                            "agreement": round(matched / max(n_ref, n_var, 1), 3),
                            "mean_score_diff": round(sdiff / max(matched, 1), 4),
                            "max_raw_class_score_diff": round(max(raw_diff), 4)}
        except BaseException as exc:  # noqa: BLE001
            res["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
            res["trace_tail"] = traceback.format_exc().splitlines()[-3:]
        results[name] = res
        out_file.write_text(json.dumps(results, indent=2))
        lat = res["latency"].get("threads_4") or next(iter(res["latency"].values()), {})
        print(f"{name:22} 4t mean={lat.get('mean_ms')} ms  drift={res.get('drift', {}).get('agreement')}  "
              f"{res.get('error', '')}", flush=True)


if __name__ == "__main__":
    main()
