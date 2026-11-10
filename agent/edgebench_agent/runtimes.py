"""Model runtimes. Each one turns a letterboxed ``(1, 3, H, W)`` float32 blob into the raw head output
``(1, 4 + classes, anchors)`` and nothing else: decoding and NMS are shared (decode.py).

A runtime whose package is not installed raises ``Unavailable``: that run is "not available", not failed.
"""

from __future__ import annotations

import importlib
import importlib.metadata
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

RUNTIME_PACKAGES = (
    "numpy",
    "onnxruntime",
    "openvino",
    "ncnn",
    "torch",
    "ultralytics",
    "opencv-python",
    "Pillow",
)


class Unavailable(Exception):
    """A package this runtime needs is not installed on this device."""


def need(module: str, package: str | None = None) -> Any:
    try:
        return importlib.import_module(module)
    except ImportError:
        raise Unavailable(f"{package or module} is not installed on this device") from None


def package_versions() -> dict[str, str]:
    found: dict[str, str] = {}
    for package in RUNTIME_PACKAGES:
        try:
            found[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            continue
    return found


class Runner:
    def run(self, blob: NDArray[np.float32]) -> NDArray[np.float32]:
        raise NotImplementedError

    def close(self) -> None:
        pass


class OnnxRunner(Runner):
    def __init__(self, path: Path, threads: int) -> None:
        ort = need("onnxruntime")
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])
        first = self.session.get_inputs()[0]
        self.name = first.name
        self.dtype = np.float16 if "float16" in first.type else np.float32

    def run(self, blob: NDArray[np.float32]) -> NDArray[np.float32]:
        out = self.session.run(None, {self.name: blob.astype(self.dtype, copy=False)})[0]
        return np.asarray(out, dtype=np.float32)


class OpenVinoRunner(Runner):
    def __init__(self, path: Path, threads: int) -> None:
        ov = need("openvino")
        core = ov.Core()
        compiled = core.compile_model(
            core.read_model(str(path)),
            "CPU",
            {"INFERENCE_NUM_THREADS": threads, "PERFORMANCE_HINT": "LATENCY"},
        )
        self.request = compiled.create_infer_request()

    def run(self, blob: NDArray[np.float32]) -> NDArray[np.float32]:
        self.request.infer({0: blob})
        return np.asarray(self.request.get_output_tensor(0).data, dtype=np.float32).copy()


class NcnnRunner(Runner):
    def __init__(self, path: Path, threads: int) -> None:
        self.ncnn = need("ncnn")
        self.net = self.ncnn.Net()
        self.net.opt.use_vulkan_compute = False
        self.net.opt.num_threads = threads
        self.net.load_param(str(path))
        self.net.load_model(str(path.with_suffix(".bin")))

    def run(self, blob: NDArray[np.float32]) -> NDArray[np.float32]:
        # ncnn.Mat keeps no reference to its source: the array must stay alive until clone() has copied it (a temporary
        # crashed the whole process in Phase 0).
        source = np.ascontiguousarray(blob[0], dtype=np.float32)
        extractor = self.net.create_extractor()
        extractor.input("in0", self.ncnn.Mat(source).clone())
        _, result = extractor.extract("out0")
        array = np.array(result, dtype=np.float32)
        return array.reshape(1, *array.shape[-2:]) if array.ndim == 2 else array


class TorchRunner(Runner):
    """TorchScript, or the original ``.pt`` through Ultralytics (the baseline every other variant is compared with)."""

    def __init__(self, path: Path, threads: int, scripted: bool) -> None:
        self.torch = need("torch")
        self.torch.set_num_threads(threads)
        if scripted:
            self.model = self.torch.jit.load(str(path), map_location="cpu").eval()
        else:
            ultralytics = need("ultralytics")
            self.model = ultralytics.YOLO(str(path)).model.float().eval()
            fuse = getattr(self.model, "fuse", None)
            if fuse is not None:
                self.model = fuse(verbose=False).eval()  # what Ultralytics does before it exports or validates

    def run(self, blob: NDArray[np.float32]) -> NDArray[np.float32]:
        with self.torch.inference_mode():
            out = self.model(self.torch.from_numpy(blob))
        out = out[0] if isinstance(out, (list, tuple)) else out
        return np.asarray(out.cpu().numpy(), dtype=np.float32)


KINDS = ("onnx", "openvino", "ncnn", "torchscript", "pytorch")


def load_runner(kind: str, path: Path, threads: int) -> Runner:
    if kind == "onnx":
        return OnnxRunner(path, threads)
    if kind == "openvino":
        return OpenVinoRunner(path, threads)
    if kind == "ncnn":
        return NcnnRunner(path, threads)
    if kind == "torchscript":
        return TorchRunner(path, threads, scripted=True)
    if kind == "pytorch":
        return TorchRunner(path, threads, scripted=False)
    raise ValueError(f"unknown runtime {kind!r}")


def kind_for_op(op: str) -> str:
    """Which runtime runs a conversion op from the server's matrix (onnx_fp16 -> onnx, ncnn_fp32 -> ncnn, ...)."""
    return "torchscript" if op == "torchscript" else op.split("_", maxsplit=1)[0]
