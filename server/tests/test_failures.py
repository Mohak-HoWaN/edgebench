"""Where a run goes wrong: pictures with a missed, wrongly named or made-up object, and the folder export."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from test_agent_api import bearer, enrolled, start_run

from edgebench import failures

NAMES = ["chips", "biscuit", "chocolate"]
CHIPS = [0, 0.25, 0.25, 0.2, 0.2]  # class, centre x, centre y, width, height: the box is 0.15 to 0.35 on both axes


def test_a_correct_detection_is_no_issue_and_a_detection_below_the_floor_is_ignored() -> None:
    r = failures.one_picture([CHIPS], NAMES, [[0.15, 0.15, 0.35, 0.35, 0.9, 0], [0.6, 0.6, 0.7, 0.7, 0.1, 1]], NAMES)
    assert r["issues"] == [] and r["severity"] == 0 and len(r["found"]) == 1


def test_wrong_name_missed_object_and_made_up_object_are_told_apart_and_weighted() -> None:
    labels = [CHIPS, [2, 0.75, 0.75, 0.3, 0.4]]
    found = [[0.15, 0.15, 0.35, 0.35, 0.8, 1], [0.0, 0.0, 0.1, 0.1, 0.7, 0]]  # chips named as biscuit; a box on nothing
    r = failures.one_picture(labels, NAMES, found, NAMES)
    kinds = sorted(i["kind"] for i in r["issues"])
    assert kinds == ["invented", "missed", "wrong"]
    wrong = next(i for i in r["issues"] if i["kind"] == "wrong")
    assert (wrong["truth"], wrong["answer"]) == ("chips", "biscuit")
    assert r["severity"] == 3 + 2 + 1


def test_a_class_the_model_does_not_have_is_left_out_like_in_the_score_and_names_not_positions_are_compared() -> None:
    model_names = ["chocolate", "chips"]  # another order
    r = failures.one_picture([CHIPS, [1, 0.5, 0.5, 0.2, 0.2]], NAMES, [[0.15, 0.15, 0.35, 0.35, 0.9, 1]], model_names)
    assert r["issues"] == []  # chips matched by name; biscuit is unknown to the model, so it is not a miss


def test_the_worst_pictures_come_first_and_pictures_without_labels_or_detections_are_skipped() -> None:
    images = [
        {"original": "a.jpg", "width": 10, "height": 10, "source": "other", "labels": [CHIPS]},
        {
            "original": "b.jpg",
            "width": 10,
            "height": 10,
            "source": "other",
            "labels": [CHIPS, [2, 0.75, 0.75, 0.3, 0.4]],
        },
        {"original": "c.jpg", "width": 10, "height": 10, "source": "other", "labels": None},
        {"original": "d.jpg", "width": 10, "height": 10, "source": "other", "labels": [CHIPS]},
    ]
    seen = {"0": [[0.15, 0.15, 0.35, 0.35, 0.9, 0]], "1": [], "2": [[0, 0, 0.1, 0.1, 0.9, 0]]}  # picture 3 was not kept
    out = failures.analyse(images, NAMES, seen, NAMES)
    assert out["checked"] == 2  # a (fine) and b; c has no labels, d has no stored detections
    assert [p["original"] for p in out["pictures"]] == ["b.jpg"]
    assert out["totals"] == {"missed": 2, "wrong": 0, "invented": 0}
    assert failures.analyse(images, NAMES, seen, NAMES, limit=1)["with_problems"] == 1


def test_the_export_is_a_folder_for_the_next_annotation_round(tmp_path: Path) -> None:
    source = tmp_path / "set.zip"
    with zipfile.ZipFile(source, "w") as z:
        z.writestr("images/000000.jpg", b"jpeg bytes")
        z.writestr("data.json", json.dumps({"images": [{"file": "images/000000.jpg"}]}))
    picked = [
        {
            "index": 0,
            "original": "shelf 1.jpg",
            **failures.one_picture([CHIPS], NAMES, [[0.0, 0.0, 0.1, 0.1, 0.9, 1]], NAMES),
        }
    ]
    with zipfile.ZipFile(io.BytesIO(failures.export(source, picked, NAMES))) as z:
        assert set(z.namelist()) == {
            "images/shelf 1.jpg",
            "labels_real/shelf 1.txt",
            "labels_from_the_model/shelf 1.txt",
            "classes.txt",
            "why.csv",
        }
        assert z.read("images/shelf 1.jpg") == b"jpeg bytes"
        assert z.read("labels_real/shelf 1.txt").decode().startswith("0 0.250000 0.250000 0.200000 0.200000")
        assert z.read("labels_from_the_model/shelf 1.txt").decode().startswith("1 0.050000 0.050000 0.100000 0.100000")
        assert "missed chips" in z.read("why.csv").decode() and "made up biscuit" in z.read("why.csv").decode()


def test_a_finished_run_lists_its_mistakes_and_exports_the_chosen_pictures(client: TestClient, tmp_path: Path) -> None:
    device_id, token = enrolled(client)
    run = start_run(client, tmp_path, device_id)
    job = client.post("/agent/claim", headers=bearer(token)).json()
    seen = {
        "min_confidence": 0.25,
        "pictures": {"0": [[0.15, 0.15, 0.35, 0.35, 0.9, 0]], "1": [[0.1, 0.1, 0.2, 0.2, 0.8, 1]]},
    }
    client.post(
        "/agent/result",
        json={"job_id": job["job_id"], "ok": True, "result": {"predictions": seen}},
        headers=bearer(token),
    )

    out = client.get(f"/api/runs/{run['id']}/failures").json()
    assert out["checked"] == 2 and out["with_problems"] == 2
    assert out["totals"] == {
        "missed": 1,
        "wrong": 0,
        "invented": 1,
    }  # the chocolate in picture 0, the made-up box in picture 1
    assert [p["index"] for p in out["pictures"]] == [0, 1]  # a miss (2) before a false alarm (1)
    zipped = client.get(f"/api/runs/{run['id']}/failures.zip?images=1,0")
    assert zipped.status_code == 200 and zipped.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(zipped.content)) as z:
        assert "why.csv" in z.namelist() and len([n for n in z.namelist() if n.startswith("images/")]) == 2
    assert client.get(f"/api/runs/{run['id']}/failures.zip?images=99").status_code == 404
    assert client.get(f"/api/runs/{run['id']}/failures.zip?images=x").status_code == 422


def test_a_run_that_kept_no_detections_says_so(client: TestClient, tmp_path: Path) -> None:
    device_id, _ = enrolled(client)
    run = start_run(client, tmp_path, device_id)
    r = client.get(f"/api/runs/{run['id']}/failures")
    assert r.status_code == 409 and "Run it again" in r.json()["detail"]
