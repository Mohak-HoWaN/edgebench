import collections, json
from pathlib import Path
import onnx
SP = Path(".").resolve(); M = SP / "models"
for name in ("yolo11n_fp32.onnx", "yolo11n_int8_dynamic.onnx", "yolo11n_int8_static_qdq.onnx", "yolo11n_int8_static_nohead.onnx"):
    ops = collections.Counter(n.op_type for n in onnx.load(str(M / name)).graph.node)
    keep = {k: v for k, v in ops.items() if k in ("Conv", "ConvInteger", "QLinearConv", "MatMulInteger", "DynamicQuantizeLinear", "QuantizeLinear", "DequantizeLinear", "MatMul")}
    print(f"{name:34} {keep}")
print()
def total(prefix):
    return sum(f.stat().st_size for f in M.glob(prefix + "*") if f.suffix in (".xml", ".bin")) / 1e6
for p in ("yolo11n_ov_fp32", "yolo11n_ov_fp16", "yolo11n_ov_int8_calib128", "yolo11n_ov_int8_calib1x10"):
    print(f"{p:34} xml+bin = {total(p):.2f} MB")