"""The whole path with the real converter environment and a real model: no fakes. Skipped where those are not available.

Set EDGEBENCH_TEST_CONVERTER_PYTHON and EDGEBENCH_TEST_PT to use other locations. Takes about two minutes.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from helpers import make_dataset

from edgebench.config import Settings
from edgebench.main import create_app
from edgebench.matrix import OPS

REPO = Path(__file__).resolve().parents[2]
PYTHON = Path(os.environ.get("EDGEBENCH_TEST_CONVERTER_PYTHON", REPO / "spikes" / ".venv" / "Scripts" / "python.exe"))
PT = Path(os.environ.get("EDGEBENCH_TEST_PT", REPO / "spikes" / "models" / "yolo11n.pt"))

pytestmark = pytest.mark.skipif(
    not (PYTHON.is_file() and PT.is_file()),
    reason="needs the converter environment and a sample model (Phase 0 spikes)",
)


def test_a_real_yolo_checkpoint_converts_to_every_format_and_matches_pytorch(settings: Settings) -> None:
    real = settings.model_copy(update={"converter_python": PYTHON, "converter_timeout_seconds": 600})
    with TestClient(create_app(real)) as c:
        info = c.get("/api/converter").json()
        assert info["available"] is True and "ultralytics" in info["versions"]

        r = c.post("/api/models", content=PT.read_bytes(), headers={"x-filename": quote(PT.name)})
        assert r.status_code == 201, r.text
        model_id = r.json()["id"]

        deadline = time.monotonic() + 420
        m = c.get(f"/api/models/{model_id}").json()
        while time.monotonic() < deadline:
            m = c.get(f"/api/models/{model_id}").json()
            if m["status"] in ("rejected", "converter_missing"):
                break  # nothing more will happen: let the assertions below say why
            done = all(v["state"] in ("ready", "failed", "unavailable") for v in m["variants"])
            if m["status"] == "ready" and len(m["variants"]) == len([o for o in OPS if not o.calibrated]) and done:
                break
            time.sleep(1)

        assert m["status"] == "ready", m["error"]
        assert m["task"] == "detect" and m["imgsz"] == 640 and len(m["class_names"]) == 80
        assert m["class_names"][0] == "person" and m["parameters"] > 2_000_000
        cells = {v["op"]: v for v in m["variants"]}
        assert {op: cells[op]["state"] for op in cells} == {op.name: "ready" for op in OPS if not op.calibrated}, {
            op: cells[op]["error"] for op in cells if cells[op]["state"] != "ready"
        }
        assert not any(v["mismatch"] for v in cells.values()), {op: v["verify"] for op, v in cells.items()}
        for op in ("onnx_fp32", "torchscript", "openvino_fp32", "ncnn_fp32"):
            assert cells[op]["verify"]["relative"] < 1e-3, (op, cells[op]["verify"])

        # What is reported is what is on disk: a bundle's size is the sum of its files.
        bundles = [d for d in (real.data_dir / "artifacts").glob("*/*") if d.is_dir() and d.name != "tmp"]
        on_disk = sorted(sum(f.stat().st_size for f in d.iterdir()) for d in bundles)
        assert sorted(v["size_bytes"] for v in cells.values()) == on_disk, "one bundle per cell, sizes as on disk"
        assert cells["openvino_fp16"]["size_bytes"] < cells["openvino_fp32"]["size_bytes"] * 0.6, (
            "FP16 weights are about half"
        )

        # INT8: calibrated on real pictures of a dataset, refused when there are too few to learn from.
        pictures = REPO / "spikes" / "data" / "coco128"
        if pictures.is_dir():
            clean = (
                settings.data_dir.parent / "coco128-clean"
            )  # only pictures and labels: a dataset refuses an Ultralytics .cache
            shutil.copytree(pictures, clean, ignore=shutil.ignore_patterns("*.cache", "LICENSE", "README.txt"))
            dataset = make_dataset(c, clean, name="coco128")
            for op in ("openvino_int8", "onnx_int8"):
                added = c.post(
                    f"/api/models/{model_id}/int8", json={"op": op, "dataset_id": dataset["id"], "count": 64, "seed": 1}
                )
                assert added.status_code == 201, added.text
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                m = c.get(f"/api/models/{model_id}").json()
                cells = {v["op"]: v for v in m["variants"]}
                if all(
                    cells[op]["state"] in ("ready", "failed", "unavailable") for op in ("openvino_int8", "onnx_int8")
                ):
                    break
                time.sleep(1)
            assert {cells[op]["state"] for op in ("openvino_int8", "onnx_int8")} == {"ready"}, {
                op: cells[op]["error"] for op in ("openvino_int8", "onnx_int8")
            }
            assert cells["openvino_int8"]["settings"]["calibration"]["count"] == 64
            assert cells["openvino_int8"]["size_bytes"] < cells["openvino_fp32"]["size_bytes"] * 0.6, (
                "INT8 weights are about a quarter"
            )
            assert cells["onnx_int8"]["size_bytes"] < cells["onnx_fp32"]["size_bytes"] * 0.6
            assert cells["onnx_int8"]["verify"]["ok"] and "drift check" in cells["onnx_int8"]["verify"]["note"]
