"""The conversion matrix: which formats and precisions exist and what each is built from (docs/phase-0-verdict.md)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Op:
    name: str
    format: str
    precision: str
    needs: str | None = None  # the op whose output this one is built from

    @property
    def label(self) -> str:
        return f"{self.format} {self.precision}"


# Order matters: a dependency comes before what needs it, and jobs run in the order they were added.
OPS: tuple[Op, ...] = (
    Op("onnx_fp32", "ONNX", "FP32"),
    Op("torchscript", "TorchScript", "FP32"),
    Op("onnx_fp16", "ONNX", "FP16", needs="onnx_fp32"),
    Op("openvino_fp32", "OpenVINO", "FP32", needs="onnx_fp32"),
    Op("openvino_fp16", "OpenVINO", "FP16", needs="onnx_fp32"),
    Op("ncnn_fp32", "ncnn", "FP32"),
    Op("ncnn_fp16", "ncnn", "FP16"),
)
BY_NAME = {op.name: op for op in OPS}


def settings_for(op: Op) -> dict[str, Any]:
    """Settings that change the output, so they belong in the cell's identity. Only the ONNX export has one."""
    return {"simplify": True} if op.name == "onnx_fp32" else {}


def settings_key(settings: dict[str, Any]) -> str:
    return json.dumps(settings, sort_keys=True)


def cache_key(model_sha: str, op: Op, imgsz: int, settings: dict[str, Any], toolchain: str) -> str:
    """ADR 0002: the same model, format, precision, size, settings and converter versions always give the same key."""
    parts = [model_sha, op.format, op.precision, str(imgsz), settings_key(settings), toolchain]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()
