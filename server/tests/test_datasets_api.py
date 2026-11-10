from __future__ import annotations

import hashlib
import http.server
import io
import json
import threading
import time
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from helpers import commit_files, folder_files, make_dataset, upload_file, wait_version
from PIL import Image
from sqlmodel import Session, select
from test_dataset_import import picture, yolo_folder

from edgebench import queue
from edgebench.config import Settings
from edgebench.main import create_app
from edgebench.models import DatasetVersion, MlModel


def jpeg(colour: tuple[int, int, int], size: tuple[int, int] = (64, 48)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, "JPEG", quality=95)
    return buf.getvalue()


def new_dataset(c: TestClient, name: str = "shelf") -> int:
    r = c.post("/api/datasets", json={"name": name, "description": "Pictures of the shelf"})
    assert r.status_code == 201
    return int(r.json()["id"])


def versions(c: TestClient, dataset_id: int) -> list[dict[str, Any]]:
    return list(c.get(f"/api/datasets/{dataset_id}").json()["versions"])


def zipped(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)), data)
    return buf.getvalue()


def engine_of(c: TestClient) -> Any:
    return c.app.state.engine  # type: ignore[attr-defined]


# --- uploading photos without any zip ---------------------------------------------------------------------------------


def test_loose_photos_without_labels_become_version_one(client: TestClient) -> None:
    dataset = new_dataset(client)
    assert client.get(f"/api/datasets/{dataset}").json()["head"] is None  # empty until something is committed
    pictures = {"a.jpg": jpeg((200, 10, 10)), "b.jpg": jpeg((10, 200, 10)), "sub/c.jpg": jpeg((10, 10, 200))}
    commit_files(client, dataset, pictures)
    v = wait_version(client, dataset)
    assert v["number"] == 1 and v["image_count"] == 3 and v["labelled_count"] == 0 and v["is_head"] and v["has_files"]
    assert any("speed runs only" in w for w in v["stats"]["warnings"])
    page = client.get(f"/api/datasets/{dataset}/versions/head/images").json()
    assert page["total"] == 3 and page["images"][0]["labels"] is None
    pic = client.get(f"/api/datasets/{dataset}/versions/1/images/0/file")
    assert pic.headers["content-type"] == "image/jpeg" and Image.open(io.BytesIO(pic.content)).size == (64, 48)
    assert client.get(f"/api/datasets/{dataset}/versions/1/images/9/file").status_code == 404


def test_pictures_with_yolo_labels_and_names_are_understood_when_uploaded_loose(
    client: TestClient, tmp_path: Path
) -> None:
    made = make_dataset(client, yolo_folder(tmp_path / "set"))
    head = made["head"]
    assert head["format"] == "yolo" and head["class_names"] == ["chips", "biscuit", "chocolate"]
    assert head["image_count"] == 2 and head["instance_count"] == 2 and head["stats"]["class_counts"] == [1, 0, 1]
    assert made["version_count"] == 1 and not made["building"]


def test_a_zip_is_still_welcome_and_is_unpacked_into_its_files(client: TestClient, tmp_path: Path) -> None:
    dataset = new_dataset(client)
    commit_files(client, dataset, {"set.zip": zipped(folder_files(yolo_folder(tmp_path / "set")))})
    v = wait_version(client, dataset)
    assert v["image_count"] == 2 and v["format"] == "yolo"
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/datasets/{dataset}/versions/1/download").content))
    assert {"images/train/a.jpg", "labels/train/a.txt", "data.yaml"} <= set(
        z.namelist()
    )  # real files, not a zip inside


def test_class_names_can_come_from_a_model_when_the_files_have_none(client: TestClient, tmp_path: Path) -> None:
    with Session(engine_of(client)) as session:
        m = MlModel(name="m", class_names=["chips", "biscuit", "chocolate"], status="ready")
        session.add(m)
        session.commit()
        session.refresh(m)
        model_id = m.id
    dataset = new_dataset(client)
    commit_files(client, dataset, folder_files(yolo_folder(tmp_path / "set", names=False)), model_id=model_id)
    v = wait_version(client, dataset)
    assert v["class_names"] == ["chips", "biscuit", "chocolate"] and not v["names_generic"]
    bad = client.post(f"/api/datasets/{dataset}/commit", json={"message": "x", "remove": ["a"], "model_id": 999})
    assert bad.status_code == 422


def test_pascal_voc_annotations_are_read(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "voc"
    picture(root / "a.jpg", size=(200, 100))
    (root / "a.xml").write_text(
        "<annotation><filename>a.jpg</filename><size><width>200</width><height>100</height></size>"
        "<object><name>chips</name><bndbox><xmin>30</xmin><ymin>15</ymin><xmax>70</xmax><ymax>35</ymax></bndbox></object>"
        "<object><name>biscuit</name><bndbox><xmin>120</xmin><ymin>55</ymin><xmax>180</xmax><ymax>95</ymax></bndbox></object>"
        "</annotation>"
    )
    made = make_dataset(client, root, "voc")
    head = made["head"]
    assert head["format"] == "voc" and head["class_names"] == ["biscuit", "chips"] and head["instance_count"] == 2
    boxes = client.get(f"/api/datasets/{made['id']}/versions/1/images").json()["images"][0]["labels"]
    assert sorted(boxes) == [[0, 0.75, 0.75, 0.3, 0.4], [1, 0.25, 0.25, 0.2, 0.2]]


# --- the history ------------------------------------------------------------------------------------------------------


def test_each_commit_is_a_version_with_a_message_and_a_change_summary(client: TestClient) -> None:
    dataset = new_dataset(client)
    commit_files(client, dataset, {"a.jpg": jpeg((200, 10, 10)), "b.jpg": jpeg((10, 200, 10))}, "First two pictures")
    wait_version(client, dataset)
    commit_files(
        client, dataset, {"c.jpg": jpeg((10, 10, 200)), "a.jpg": jpeg((250, 10, 10))}, "A third, a.jpg retaken"
    )
    v2 = wait_version(client, dataset, "2")
    assert v2["message"] == "A third, a.jpg retaken" and v2["image_count"] == 3
    assert (v2["changes"]["added"], v2["changes"]["modified"], v2["changes"]["removed"]) == (1, 1, 0)
    assert v2["changes"]["added_paths"] == ["c.jpg"] and v2["changes"]["modified_paths"] == ["a.jpg"]
    assert [(v["number"], v["is_head"]) for v in versions(client, dataset)] == [(2, True), (1, False)]
    assert client.get(f"/api/datasets/{dataset}/versions/1").json()["image_count"] == 2  # older versions are untouched


def test_removing_files_makes_a_version_without_them(client: TestClient) -> None:
    dataset = new_dataset(client)
    commit_files(
        client, dataset, {"keep.jpg": jpeg((1, 2, 3)), "old/x.jpg": jpeg((9, 9, 9)), "old/y.jpg": jpeg((8, 8, 8))}
    )
    wait_version(client, dataset)
    r = client.post(f"/api/datasets/{dataset}/commit", json={"message": "Drop the old folder", "remove": ["old"]})
    assert r.status_code == 202
    v = wait_version(client, dataset, "2")
    assert (
        v["image_count"] == 1
        and v["changes"]["removed"] == 2
        and v["changes"]["removed_paths"] == ["old/x.jpg", "old/y.jpg"]
    )


def test_a_commit_that_changes_nothing_is_refused_with_the_reason_and_can_be_discarded(client: TestClient) -> None:
    dataset = new_dataset(client)
    commit_files(client, dataset, {"a.jpg": jpeg((200, 10, 10))})
    wait_version(client, dataset)
    commit_files(client, dataset, {"a.jpg": jpeg((200, 10, 10))}, "The same again")
    failed = wait_version(client, dataset, "2", "failed")
    assert "Nothing changed compared with version 1" in failed["error"]
    assert client.get(f"/api/datasets/{dataset}").json()["head"]["number"] == 1  # the head did not move
    assert client.delete(f"/api/datasets/{dataset}/versions/1").status_code == 409  # a finished version is history
    assert client.delete(f"/api/datasets/{dataset}/versions/2").status_code == 204
    assert [v["number"] for v in versions(client, dataset)] == [1]


def test_an_old_version_can_be_restored_without_losing_the_history(client: TestClient) -> None:
    dataset = new_dataset(client)
    commit_files(client, dataset, {"a.jpg": jpeg((200, 10, 10)), "b.jpg": jpeg((10, 200, 10))}, "Two")
    wait_version(client, dataset)
    commit_files(client, dataset, {"c.jpg": jpeg((10, 10, 200))}, "Three")
    wait_version(client, dataset, "2")
    assert client.post(f"/api/datasets/{dataset}/versions/2/restore").status_code == 202  # it is the head already
    assert "Nothing changed" in wait_version(client, dataset, "3", "failed")["error"]
    client.delete(f"/api/datasets/{dataset}/versions/3")

    r = client.post(f"/api/datasets/{dataset}/versions/1/restore")
    assert r.status_code == 202 and r.json()["message"] == "Restore version 1"
    v3 = wait_version(client, dataset, "3")
    assert v3["image_count"] == 2 and v3["changes"]["removed_paths"] == ["c.jpg"]
    assert [v["number"] for v in versions(client, dataset)] == [3, 2, 1]  # nothing was deleted
    assert client.get(f"/api/datasets/{dataset}/versions/2").json()["image_count"] == 3
    assert client.post(f"/api/datasets/{dataset}/versions/9/restore").status_code == 404


def test_versions_download_as_the_original_files_or_the_normalised_copy(client: TestClient, tmp_path: Path) -> None:
    files = folder_files(yolo_folder(tmp_path / "set"))
    dataset = make_dataset(client, tmp_path / "set", "My shelf!")["id"]
    original = client.get(f"/api/datasets/{dataset}/versions/1/download")
    assert 'filename="My_shelf-v1.zip"' in original.headers["content-disposition"]
    z = zipfile.ZipFile(io.BytesIO(original.content))
    assert {n: z.read(n) for n in z.namelist()} == files  # byte for byte what was uploaded
    normalised = client.get(f"/api/datasets/{dataset}/versions/head/download?kind=normalised")
    assert "My_shelf-v1-normalised.zip" in normalised.headers["content-disposition"]
    assert "data.json" in zipfile.ZipFile(io.BytesIO(normalised.content)).namelist()
    assert client.get(f"/api/datasets/{dataset}/versions/1/download?kind=nope").status_code == 422
    # a version made before versions existed has no original files to give back
    with Session(engine_of(client)) as session:
        row = session.exec(select(DatasetVersion)).first()
        assert row is not None
        row.manifest = None
        session.add(row)
        session.commit()
    legacy = client.get(f"/api/datasets/{dataset}/versions/1/download")
    assert legacy.status_code == 409 and "normalised" in legacy.json()["detail"]
    assert client.post(f"/api/datasets/{dataset}/versions/1/restore").status_code == 409
    assert client.get(f"/api/datasets/{dataset}/versions/1/download?kind=normalised").status_code == 200


# --- sharing ----------------------------------------------------------------------------------------------------------


def test_a_dataset_is_shared_as_a_bundle_and_imported_with_its_whole_history(client: TestClient) -> None:
    dataset = new_dataset(client, "Shared shelf")
    commit_files(client, dataset, {"a.jpg": jpeg((200, 10, 10)), "b.jpg": jpeg((10, 200, 10))}, "Two pictures")
    wait_version(client, dataset)
    commit_files(client, dataset, {"c.jpg": jpeg((10, 10, 200))}, "A third")
    wait_version(client, dataset, "2")
    bundle = client.get(f"/api/datasets/{dataset}/export")
    assert bundle.status_code == 200 and "Shared_shelf.ebdataset.zip" in bundle.headers["content-disposition"]

    r = client.post(
        "/api/datasets/import-bundle?name=Copy", content=bundle.content, headers={"x-filename": "shelf.zip"}
    )
    assert r.status_code == 202 and r.json()["name"] == "Copy"
    copy = r.json()["id"]
    wait_version(client, copy, "2")
    original, imported = versions(client, dataset), versions(client, copy)
    assert [(v["number"], v["message"], v["dataset_hash"]) for v in imported] == [
        (v["number"], v["message"], v["dataset_hash"]) for v in original
    ]  # the same history with the same content
    assert client.get(f"/api/datasets/{copy}/versions/1").json()["image_count"] == 2


def test_a_file_that_is_not_a_bundle_is_reported_on_the_new_dataset(client: TestClient) -> None:
    r = client.post(
        "/api/datasets/import-bundle", content=zipped({"notes.txt": b"hi"}), headers={"x-filename": "x.zip"}
    )
    failed = wait_version(client, r.json()["id"], "1", "failed")
    assert "not a readable EdgeBench dataset bundle" in failed["error"]
    assert (
        client.post("/api/datasets/import-bundle", content=b"nope", headers={"x-filename": "x.zip"}).status_code == 422
    )


def test_a_bundle_with_a_damaged_file_is_refused(client: TestClient) -> None:
    claimed = jpeg((7, 8, 9))  # the checksum the bundle promises ...
    promised = hashlib.sha256(claimed).hexdigest()
    description = {
        "format": "edgebench-dataset",
        "version": 1,
        "name": "Damaged",
        "versions": [
            {"number": 1, "message": "x", "manifest": [{"path": "a.jpg", "sha256": promised, "size": len(claimed)}]}
        ],
    }
    bundle = zipped(
        {"edgebench-dataset.json": json.dumps(description).encode(), f"blobs/{promised}": b"not that picture"}
    )
    r = client.post("/api/datasets/import-bundle", content=bundle, headers={"x-filename": "d.zip"})
    assert (
        "does not match its checksum" in wait_version(client, r.json()["id"], "1", "failed")["error"]
    )  # ... and the content


# --- refusals ---------------------------------------------------------------------------------------------------------


def test_uploads_are_checked_before_anything_is_kept(client: TestClient) -> None:
    dataset = new_dataset(client)
    url = f"/api/datasets/{dataset}/blobs"

    def put(path: str, data: bytes = b"x") -> Any:
        return client.post(url, content=data, headers={"x-path": path})

    assert "not a kind of file" in put("run.exe").json()["detail"]
    assert "HEIC" in put("p.heic").json()["detail"]
    assert put("../escape.jpg").status_code == 422 and put("C:/x.jpg").status_code == 422
    assert put("empty.jpg", b"").status_code == 422
    assert client.post("/api/datasets/999/blobs", content=b"x", headers={"x-path": "a.jpg"}).status_code == 404
    unknown = client.post(f"/api/datasets/{dataset}/commit", json={"add": [{"path": "a.jpg", "sha256": "0" * 64}]})
    assert unknown.status_code == 422 and "was not uploaded" in unknown.json()["detail"]
    assert client.post(f"/api/datasets/{dataset}/commit", json={"add": []}).status_code == 422
    assert client.post("/api/datasets", json={"name": ""}).status_code == 422


def test_a_bad_label_fails_the_version_with_the_file_and_line(client: TestClient, tmp_path: Path) -> None:
    dataset = new_dataset(client)
    commit_files(client, dataset, folder_files(yolo_folder(tmp_path / "set", rows=["0 0.5 0.5"])))
    assert "labels/train/a.txt line 1" in wait_version(client, dataset, "1", "failed")["error"]


def test_a_zip_with_unsafe_paths_or_no_pictures_fails_with_the_reason(client: TestClient) -> None:
    dataset = new_dataset(client)
    commit_files(client, dataset, {"bad.zip": zipped({"../escape.jpg": b"x", "ok.jpg": b"x"})})
    assert "not a safe path" in wait_version(client, dataset, "1", "failed")["error"]
    commit_files(client, dataset, {"notes.zip": zipped({"notes.txt": b"hi"})})
    assert "No images were found" in wait_version(client, dataset, "2", "failed")["error"]


def test_a_picture_that_cannot_be_read_names_itself(client: TestClient) -> None:
    dataset = new_dataset(client)
    commit_files(client, dataset, {"ok.jpg": jpeg((1, 2, 3)), "broken.jpg": b"this is not a picture"})
    assert "broken.jpg could not be read" in wait_version(client, dataset, "1", "failed")["error"]


def test_the_calibration_subset_is_chosen_per_version_and_needs_fifty_pictures(
    client: TestClient, tmp_path: Path
) -> None:
    small = make_dataset(client, yolo_folder(tmp_path / "small"), "small")
    refused = client.post(f"/api/datasets/{small['id']}/versions/head/calibration", json={})
    assert refused.status_code == 422 and "at least 50" in refused.json()["detail"]

    dataset = new_dataset(client, "big")
    pictures = {f"{'rpi-cam3-wide' if i % 3 == 0 else 'mobile'}/{i}.jpg": jpeg((i, i, i)) for i in range(60)}
    commit_files(client, dataset, pictures)
    wait_version(client, dataset)
    chosen = client.post(f"/api/datasets/{dataset}/versions/1/calibration", json={"count": 51, "seed": 3}).json()
    assert chosen["calibration"]["count"] == 51 and len(chosen["calibration"]["files"]) == 51
    assert client.get(f"/api/datasets/{dataset}/versions/1").json()["calibration"] == {"seed": 3, "count": 51}
    assert {d["name"]: d["head"]["calibration"] for d in client.get("/api/datasets").json()}["big"] == {
        "seed": 3,
        "count": 51,
    }


# --- folders on this machine ------------------------------------------------------------------


def test_a_folder_on_this_machine_becomes_a_version_and_can_be_added_to(client: TestClient, tmp_path: Path) -> None:
    folder = yolo_folder(tmp_path / "local")
    r = client.post("/api/datasets/from-folder", json={"path": str(folder)})
    assert r.status_code == 202 and r.json()["name"] == "local"
    dataset = r.json()["id"]
    v = wait_version(client, dataset)
    assert v["image_count"] == 2 and v["source_path"] == str(folder) and v["message"] == "Import local"

    more = tmp_path / "more"
    picture(more / "extra.jpg")
    again = client.post(
        "/api/datasets/from-folder", json={"path": str(more), "dataset_id": dataset, "message": "Extra"}
    )
    assert again.json()["id"] == dataset
    v2 = wait_version(client, dataset, "2")
    assert v2["image_count"] == 3 and v2["changes"]["added_paths"] == ["extra.jpg"]
    assert client.post("/api/datasets/from-folder", json={"path": str(tmp_path / "nope")}).status_code == 422
    assert client.post("/api/datasets/from-folder", json={"path": "relative/dir"}).status_code == 422


# --- housekeeping -----------------------------------------------------------------------------------------------------


def test_a_dataset_can_be_renamed_and_removed(client: TestClient) -> None:
    dataset = new_dataset(client, "old name")
    r = client.patch(f"/api/datasets/{dataset}", json={"name": "new name", "description": "why this exists"})
    assert r.json()["name"] == "new name" and r.json()["description"] == "why this exists"
    assert client.delete(f"/api/datasets/{dataset}").status_code == 204
    assert client.get(f"/api/datasets/{dataset}").status_code == 404
    assert client.get("/api/datasets").json() == []


def test_a_dataset_removed_while_it_is_building_ends_quietly(client: TestClient) -> None:
    dataset = new_dataset(client)
    commit_files(client, dataset, {"a.jpg": jpeg((1, 2, 3))})
    client.delete(f"/api/datasets/{dataset}")
    time.sleep(1.0)
    assert client.get("/api/health").json()["queue"]["failed"] == 0


def test_a_second_commit_waits_for_the_one_still_being_built(client: TestClient) -> None:
    dataset = new_dataset(client)
    file = upload_file(client, dataset, "a.jpg", jpeg((1, 2, 3)))
    with Session(engine_of(client)) as session:  # a version row that never finishes, as a very slow import would leave
        session.add(DatasetVersion(dataset_id=dataset, number=1, status="building"))
        session.commit()
    refused = client.post(
        f"/api/datasets/{dataset}/commit", json={"add": [{"path": file["path"], "sha256": file["sha256"]}]}
    )
    assert refused.status_code == 409 and "still being built" in refused.json()["detail"]
    assert client.post(f"/api/datasets/{dataset}/versions/1/restore").status_code == 409


def test_a_cross_site_page_cannot_change_a_dataset(client: TestClient, tmp_path: Path) -> None:
    hostile = {"origin": "https://evil.example"}
    dataset = new_dataset(client)
    assert client.post("/api/datasets", json={"name": "x"}, headers=hostile).status_code == 403
    assert (
        client.post(f"/api/datasets/{dataset}/blobs", content=b"x", headers={**hostile, "x-path": "a.jpg"}).status_code
        == 403
    )
    assert client.post(f"/api/datasets/{dataset}/commit", json={}, headers=hostile).status_code == 403
    assert client.post(f"/api/datasets/{dataset}/versions/1/restore", headers=hostile).status_code == 403
    assert client.patch(f"/api/datasets/{dataset}", json={"name": "y"}, headers=hostile).status_code == 403
    assert client.delete(f"/api/datasets/{dataset}", headers=hostile).status_code == 403
    assert client.post("/api/datasets/from-folder", json={"path": str(tmp_path)}, headers=hostile).status_code == 403
    assert (
        client.post("/api/datasets/import-bundle", content=b"x", headers={**hostile, "x-filename": "a.zip"}).status_code
        == 403
    )


def test_the_agent_jobs_are_not_taken_by_the_servers_own_worker(client: TestClient) -> None:
    engine = engine_of(client)
    job = queue.enqueue(engine, "benchmark", {"x": 1}, device_id=5)
    time.sleep(0.5)  # the worker polls every 50 ms in these tests
    assert queue.get(engine, job).state == "queued"  # type: ignore[union-attr]
    claimed = queue.claim(engine, "agent-5", device_id=5)
    assert claimed is not None and claimed.id == job
    other = queue.enqueue(engine, "benchmark", {}, device_id=6)
    assert queue.claim(engine, "agent-5", device_id=5) is None  # another device's job is not ours
    assert queue.claim(engine, "agent-6", device_id=6) is not None and other


# --- NDJSON datasets (the Ultralytics format) ---------------------------------------------------


def ndjson(*lines: dict[str, Any]) -> bytes:
    return "\n".join(json.dumps(line) for line in lines).encode()


DATASET_LINE = {"type": "dataset", "task": "detect", "name": "shelf", "class_names": {"0": "chips", "1": "biscuit"}}


def test_an_ndjson_file_with_its_pictures_is_a_dataset(client: TestClient) -> None:
    dataset = new_dataset(client)
    lines = ndjson(
        DATASET_LINE,
        {"type": "image", "file": "a.jpg", "split": "train", "annotations": {"boxes": [[0, 0.5, 0.5, 0.2, 0.4]]}},
        {
            "type": "image",
            "file": "b.jpg",
            "split": "val",
            "annotations": {"boxes": [[1, 0.25, 0.25, 0.1, 0.1], [0, 0.7, 0.7, 0.2, 0.2]]},
        },
        {"type": "image", "file": "c.jpg", "split": "val", "annotations": {"boxes": []}},
    )
    commit_files(
        client,
        dataset,
        {
            "shelf.ndjson": lines,
            "a.jpg": jpeg((200, 10, 10)),
            "b.jpg": jpeg((10, 200, 10)),
            "c.jpg": jpeg((10, 10, 200)),
        },
        "From ndjson",
    )
    v = wait_version(client, dataset)
    assert v["image_count"] == 3 and v["format"] == "yolo" and v["class_names"] == ["chips", "biscuit"]
    assert v["labelled_count"] == 3 and v["instance_count"] == 3 and v["stats"]["class_counts"] == [2, 1]
    files = zipfile.ZipFile(io.BytesIO(client.get(f"/api/datasets/{dataset}/versions/1/download").content)).namelist()
    assert {"images/train/a.jpg", "images/val/b.jpg", "labels/val/b.txt", "data.yaml"} <= set(files)
    assert (
        "a.jpg" not in files and "shelf.ndjson" not in files
    )  # the pictures moved into the layout; the file itself is spent


def test_ndjson_lines_without_annotations_are_unlabelled_pictures(client: TestClient) -> None:
    dataset = new_dataset(client)
    commit_files(
        client,
        dataset,
        {"x.ndjson": ndjson(DATASET_LINE, {"type": "image", "file": "a.jpg"}), "a.jpg": jpeg((1, 2, 3))},
    )
    v = wait_version(client, dataset)
    assert v["image_count"] == 1 and v["labelled_count"] == 0


def test_ndjson_problems_are_reported_in_words(client: TestClient) -> None:
    dataset = new_dataset(client)
    commit_files(client, dataset, {"bad.ndjson": b'{"type": "dataset"}\nnot json\n'})
    assert "Line 2 of the NDJSON file is not valid JSON" in wait_version(client, dataset, "1", "failed")["error"]
    commit_files(client, dataset, {"none.ndjson": ndjson(DATASET_LINE)})
    assert "no image lines" in wait_version(client, dataset, "2", "failed")["error"]
    commit_files(client, dataset, {"gone.ndjson": ndjson(DATASET_LINE, {"type": "image", "file": "nowhere.jpg"})})
    assert "nowhere.jpg" in wait_version(client, dataset, "3", "failed")["error"]
    badbox = ndjson({"type": "image", "file": "a.jpg", "annotations": {"boxes": [[0, 1]]}})
    commit_files(client, dataset, {"box.ndjson": badbox, "a.jpg": jpeg((1, 2, 3))})
    assert "a box must be" in wait_version(client, dataset, "4", "failed")["error"]


class _Images(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/go":
            self.send_response(302)
            self.send_header("Location", "/a.jpg")
            self.end_headers()
            return
        body = jpeg((9, 99, 199)) if self.path.endswith(".jpg") else b"missing"
        self.send_response(200 if self.path.endswith(".jpg") else 404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_: Any) -> None:
        pass


@pytest.fixture
def image_server() -> Any:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Images)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_ndjson_pictures_are_fetched_from_their_addresses_only_when_allowed(
    settings: Settings, image_server: str
) -> None:
    lines = ndjson(
        DATASET_LINE,
        {
            "type": "image",
            "file": "a.jpg",
            "url": f"{image_server}/a.jpg",
            "annotations": {"boxes": [[0, 0.5, 0.5, 0.2, 0.2]]},
        },
        {
            "type": "image",
            "file": "b.jpg",
            "url": f"{image_server}/go",
            "annotations": {"boxes": []},
        },  # follows a redirect
    )
    # by default a local address is refused: a file someone else wrote must not make the server look at its own network
    with TestClient(create_app(settings)) as c:
        dataset = new_dataset(c)
        commit_files(c, dataset, {"web.ndjson": lines})
        assert "is not a public address" in wait_version(c, dataset, "1", "failed")["error"]
    with TestClient(create_app(settings.model_copy(update={"allow_private_ndjson_urls": True}))) as c:
        dataset = new_dataset(c)
        commit_files(c, dataset, {"web.ndjson": lines})
        v = wait_version(c, dataset)
        assert v["image_count"] == 2 and v["instance_count"] == 1 and v["class_names"] == ["chips", "biscuit"]
        dead = ndjson({"type": "image", "file": "z.jpg", "url": f"{image_server}/z.png"})
        commit_files(c, dataset, {"dead.ndjson": dead})
        assert "answered 404" in wait_version(c, dataset, "2", "failed")["error"]
        scheme = ndjson({"type": "image", "file": "z.jpg", "url": "file:///etc/passwd"})
        commit_files(c, dataset, {"scheme.ndjson": scheme})
        assert "not an http or https address" in wait_version(c, dataset, "3", "failed")["error"]
