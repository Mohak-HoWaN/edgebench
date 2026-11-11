"""INT8 conversions: calibrated on a dataset's pictures, not part of "convert everything", refused with too few."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from helpers import make_dataset
from test_dataset_import import picture
from test_models_api import by_op, settled, upload, wait


def many_pictures(root: Path, count: int) -> Path:
    for i in range(count):
        picture(root / "images" / "train" / f"p{i:03d}.jpg", colour=(i * 4 % 256, 255 - i * 3 % 256, i * 7 % 256))
    (root / "labels" / "train").mkdir(parents=True)
    for i in range(count):
        (root / "labels" / "train" / f"p{i:03d}.txt").write_text("0 0.5 0.5 0.4 0.4\n")
    (root / "data.yaml").write_text("names:\n  0: chips\n")
    return root


def copies_of_one_picture(root: Path, count: int) -> Path:
    """The old recipe: one picture, over and over, under different names."""
    for i in range(count):
        picture(root / "images" / "train" / f"p{i:03d}.jpg", colour=(10, 200, 30))
    (root / "labels" / "train").mkdir(parents=True)
    for i in range(count):
        (root / "labels" / "train" / f"p{i:03d}.txt").write_text("0 0.5 0.5 0.4 0.4\n")
    (root / "data.yaml").write_text("names:\n  0: chips\n")
    return root


def ready_model(c: TestClient) -> int:
    model_id = int(upload(c).json()["id"])
    wait(lambda: settled(c, model_id))
    return model_id


def add_int8(c: TestClient, model_id: int, dataset_id: int, op: str = "openvino_int8", **extra: Any) -> Any:
    return c.post(f"/api/models/{model_id}/int8", json={"op": op, "dataset_id": dataset_id, **extra})


def test_an_int8_conversion_is_calibrated_on_the_datasets_pictures_and_remembers_which(
    mclient: TestClient, tmp_path: Path
) -> None:
    model_id = ready_model(mclient)
    dataset = make_dataset(mclient, many_pictures(tmp_path / "ds", 64))
    r = add_int8(mclient, model_id, dataset["id"], count=60, seed=3)
    assert r.status_code == 201, r.text
    wait(lambda: by_op(mclient, model_id)["openvino_int8"]["state"] == "ready")
    cell = by_op(mclient, model_id)["openvino_int8"]
    calibration = cell["settings"]["calibration"]
    assert calibration["count"] == 60 and calibration["seed"] == 3 and calibration["version"] == 1
    assert len(calibration["list_sha"]) == 64 and cell["verify"]["ok"]
    assert (mclient.app.state.services.store.path(calibration["list_sha"])).is_file()  # type: ignore[attr-defined]


def test_the_converter_is_given_exactly_the_calibration_pictures(mclient: TestClient, tmp_path: Path) -> None:
    model_id = ready_model(mclient)
    dataset = make_dataset(mclient, many_pictures(tmp_path / "ds", 64))
    add_int8(mclient, model_id, dataset["id"], count=52, seed=0)
    wait(lambda: by_op(mclient, model_id)["openvino_int8"]["state"] == "ready")
    bundle = mclient.get(f"/api/variants/{by_op(mclient, model_id)['openvino_int8']['id']}/download")
    assert bundle.status_code == 200
    with zipfile.ZipFile(io.BytesIO(bundle.content)) as z:
        given = z.read(next(n for n in z.namelist() if n.endswith("calibration.txt"))).decode().splitlines()
    assert len(given) == 52 and len(set(given)) == 52 and all(n.endswith(".jpg") for n in given)


def test_fewer_than_fifty_pictures_are_refused_with_the_reason(mclient: TestClient, tmp_path: Path) -> None:
    model_id = ready_model(mclient)
    dataset = make_dataset(mclient, many_pictures(tmp_path / "ds", 12))
    r = add_int8(mclient, model_id, dataset["id"])
    assert r.status_code == 422 and "at least 50" in r.json()["detail"] and "12" in r.json()["detail"]
    assert "openvino_int8" not in by_op(mclient, model_id)  # nothing was created


def test_copies_of_one_picture_do_not_count_as_fifty_pictures(mclient: TestClient, tmp_path: Path) -> None:
    """One picture repeated gave a worse INT8 model than 128 different ones (docs/phase-0-verdict.md)."""
    model_id = ready_model(mclient)
    dataset = make_dataset(mclient, copies_of_one_picture(tmp_path / "ds", 60))
    r = add_int8(mclient, model_id, dataset["id"], count=50)
    assert r.status_code == 422 and "50 different pictures" in r.json()["detail"] and "has 1" in r.json()["detail"]
    assert "copies of those" in r.json()["detail"]
    assert "openvino_int8" not in by_op(mclient, model_id)


def test_int8_is_not_part_of_convert_everything_and_needs_the_fp32_onnx_it_is_built_from(
    mclient: TestClient, tmp_path: Path
) -> None:
    model_id = ready_model(mclient)
    assert not any(op.endswith("int8") for op in by_op(mclient, model_id))
    dataset = make_dataset(mclient, many_pictures(tmp_path / "ds", 60))
    assert add_int8(mclient, model_id, dataset["id"], op="onnx_int8").status_code == 201
    wait(lambda: by_op(mclient, model_id)["onnx_int8"]["state"] == "ready")
    assert by_op(mclient, model_id)["onnx_fp32"]["state"] == "ready"  # the source the INT8 file was quantized from


def test_the_same_calibration_is_one_variant_and_a_different_one_is_another(
    mclient: TestClient, tmp_path: Path
) -> None:
    model_id = ready_model(mclient)
    dataset = make_dataset(mclient, many_pictures(tmp_path / "ds", 64))
    for seed in (1, 1, 2):
        assert add_int8(mclient, model_id, dataset["id"], count=50, seed=seed).status_code == 201
    wait(lambda: all(v["state"] == "ready" for v in mclient.get(f"/api/models/{model_id}").json()["variants"]))
    int8 = [v for v in mclient.get(f"/api/models/{model_id}").json()["variants"] if v["op"] == "openvino_int8"]
    assert sorted(v["settings"]["calibration"]["seed"] for v in int8) == [1, 2]


def test_only_int8_operations_and_real_datasets_are_accepted(mclient: TestClient, tmp_path: Path) -> None:
    model_id = ready_model(mclient)
    dataset = make_dataset(mclient, many_pictures(tmp_path / "ds", 60))
    assert "not an INT8" in add_int8(mclient, model_id, dataset["id"], op="onnx_fp16").json()["detail"]
    assert add_int8(mclient, model_id, dataset["id"], op="nope").status_code == 422
    assert add_int8(mclient, model_id, 999).status_code == 422
    assert add_int8(mclient, model_id, dataset["id"], imgsz=330).status_code == 422
    assert add_int8(mclient, 999, dataset["id"]).status_code == 404
