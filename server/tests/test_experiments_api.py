"""Experiments: one named group of runs, one row on the Results page."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from test_agent_api import bearer, enrolled, seed_dataset, seed_model

RESULT = {"speed": {"stages": {"total": {"p50": 12.0}}}, "accuracy": {"available": False}}


def start(
    c: TestClient, tmp_path: Path, device_id: int, name: str = "Does FP16 hurt?", baseline: bool = True
) -> dict[str, Any]:
    model_id, variant_id = seed_model(c, tmp_path)
    items: list[dict[str, Any]] = [{"model_id": model_id, "variant_id": variant_id}]
    if baseline:
        items.append({"model_id": model_id, "variant_id": None})
    r = c.post(
        "/api/experiments",
        json={
            "name": name,
            "notes": "Checking the conversions",
            "dataset_id": seed_dataset(c, tmp_path),
            "device_id": device_id,
            "params": {"threads": 2, "warmup": 1, "iterations": 5},
            "items": items,
        },
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


def finish_all(c: TestClient, token: str, ok: bool = True) -> None:
    while (claimed := c.post("/agent/claim", headers=bearer(token))).status_code == 200:
        body = {
            "job_id": claimed.json()["job_id"],
            "ok": ok,
            "result": RESULT if ok else None,
            "error": None if ok else "boom",
        }
        c.post("/agent/result", json=body, headers=bearer(token))


def test_an_experiment_is_one_row_that_holds_a_run_per_variant(client: TestClient, tmp_path: Path) -> None:
    device_id, token = enrolled(client)
    e = start(client, tmp_path, device_id)
    assert e["name"] == "Does FP16 hurt?" and e["notes"] == "Checking the conversions"
    assert e["status"] == "running" and e["counts"] == {"queued": 2} and e["models"] == ["retail"]
    assert e["dataset_name"] == "shelf" and e["dataset_version"] == 1 and e["device_name"] == "this PC"
    assert [r["variant_label"] for r in e["runs"]] == ["ONNX FP32", "PyTorch (.pt) baseline"]
    assert all(r["experiment_id"] == e["id"] for r in e["runs"])

    listed = client.get("/api/experiments").json()
    assert [x["id"] for x in listed] == [e["id"]] and len(listed[0]["runs"]) == 2  # one row, its runs inside

    finish_all(client, token)
    done = client.get(f"/api/experiments/{e['id']}").json()
    assert done["status"] == "done" and done["counts"] == {"done": 2}
    assert [r["id"] for r in client.get(f"/api/runs?experiment_id={e['id']}").json()] == [
        r["id"] for r in reversed(done["runs"])
    ]


def test_an_experiment_with_a_failed_run_is_partly_done(client: TestClient, tmp_path: Path) -> None:
    device_id, token = enrolled(client)
    e = start(client, tmp_path, device_id)
    first = client.post("/agent/claim", headers=bearer(token)).json()
    client.post("/agent/result", json={"job_id": first["job_id"], "ok": True, "result": RESULT}, headers=bearer(token))
    second = client.post("/agent/claim", headers=bearer(token)).json()
    client.post(
        "/agent/result",
        json={"job_id": second["job_id"], "ok": False, "kind": "unavailable", "error": "torch is not installed"},
        headers=bearer(token),
    )
    got = client.get(f"/api/experiments/{e['id']}").json()
    assert got["status"] == "partly" and got["counts"] == {"done": 1, "unavailable": 1}


def test_nothing_is_created_if_any_item_is_not_ready(client: TestClient, tmp_path: Path) -> None:
    device_id, _ = enrolled(client)
    model_id, variant_id = seed_model(client, tmp_path)
    body = {
        "name": "all or nothing",
        "dataset_id": seed_dataset(client, tmp_path),
        "device_id": device_id,
        "items": [{"model_id": model_id, "variant_id": variant_id}, {"model_id": model_id, "variant_id": 999}],
    }
    r = client.post("/api/experiments", json=body)
    assert r.status_code == 422 and "does not belong" in r.json()["detail"]
    assert client.get("/api/experiments").json() == [] and client.get("/api/runs").json() == []
    assert client.post("/api/experiments", json={**body, "items": []}).status_code == 422
    assert client.post("/api/experiments", json={**body, "name": ""}).status_code == 422


def test_the_same_item_twice_makes_one_run(client: TestClient, tmp_path: Path) -> None:
    device_id, _ = enrolled(client)
    model_id, variant_id = seed_model(client, tmp_path)
    r = client.post(
        "/api/experiments",
        json={
            "name": "dupes",
            "dataset_id": seed_dataset(client, tmp_path),
            "device_id": device_id,
            "items": [{"model_id": model_id, "variant_id": variant_id}] * 3,
        },
    )
    assert len(r.json()["runs"]) == 1


def test_settings_that_the_device_cannot_do_stop_the_whole_experiment(client: TestClient, tmp_path: Path) -> None:
    created = client.post("/api/devices", json={"name": "small", "expected_kind": "pc"}).json()
    client.post(
        "/agent/enroll",
        json={"token": created["enroll_token"], "fingerprint": {"logical_cores": 4, "pi_model": None}},
    )
    model_id, variant_id = seed_model(client, tmp_path)
    r = client.post(
        "/api/experiments",
        json={
            "name": "too many threads",
            "dataset_id": seed_dataset(client, tmp_path),
            "device_id": created["device"]["id"],
            "params": {"threads": 16},
            "items": [{"model_id": model_id, "variant_id": variant_id}],
        },
    )
    assert r.status_code == 422 and "16 threads do not fit on the device's 4 CPUs" in r.json()["detail"]
    assert client.get("/api/experiments").json() == []


def test_cancelling_an_experiment_stops_what_is_left_and_only_then_can_it_be_removed(
    client: TestClient, tmp_path: Path
) -> None:
    device_id, token = enrolled(client)
    e = start(client, tmp_path, device_id)
    first = client.post("/agent/claim", headers=bearer(token)).json()  # one run is now running, one waits
    cancelled = client.post(f"/api/experiments/{e['id']}/cancel").json()
    assert {r["status"] for r in cancelled["runs"]} == {
        "running",
        "cancelled",
    }  # the running one is asked, the waiting one stops
    client.post(
        "/agent/result", json={"job_id": first["job_id"], "ok": False, "kind": "cancelled"}, headers=bearer(token)
    )
    assert client.get(f"/api/experiments/{e['id']}").json()["status"] == "partly"
    assert client.post(f"/api/experiments/{e['id']}/cancel").status_code == 409  # nothing left to stop

    assert client.delete(f"/api/experiments/{e['id']}").status_code == 204
    assert client.get(f"/api/experiments/{e['id']}").status_code == 404
    assert client.get("/api/runs").json() == [] and client.get("/api/experiments").json() == []


def test_running_a_run_again_keeps_it_in_its_experiment(client: TestClient, tmp_path: Path) -> None:
    device_id, token = enrolled(client)
    e = start(client, tmp_path, device_id, baseline=False)
    finish_all(client, token)
    again = client.post(f"/api/runs/{e['runs'][0]['id']}/again").json()
    assert again["experiment_id"] == e["id"]
    assert len(client.get(f"/api/experiments/{e['id']}").json()["runs"]) == 2


def test_removing_one_run_leaves_the_experiment_and_a_cross_site_page_cannot_touch_either(
    client: TestClient, tmp_path: Path
) -> None:
    device_id, token = enrolled(client)
    e = start(client, tmp_path, device_id)
    finish_all(client, token)
    assert client.delete(f"/api/runs/{e['runs'][0]['id']}").status_code == 204
    assert len(client.get(f"/api/experiments/{e['id']}").json()["runs"]) == 1
    hostile = {"origin": "https://evil.example"}
    assert client.post("/api/experiments", json={}, headers=hostile).status_code == 403
    assert client.post(f"/api/experiments/{e['id']}/cancel", headers=hostile).status_code == 403
    assert client.delete(f"/api/experiments/{e['id']}", headers=hostile).status_code == 403
    assert client.get("/api/experiments/999").status_code == 404


def test_an_experiment_can_be_removed_even_while_it_runs_and_a_late_result_is_ignored(
    client: TestClient, tmp_path: Path
) -> None:
    device_id, token = enrolled(client)
    e = start(client, tmp_path, device_id)
    running = client.post("/agent/claim", headers=bearer(token)).json()  # one run is on the agent, one waits
    assert client.delete(f"/api/experiments/{e['id']}").status_code == 204
    assert client.get("/api/runs").json() == [] and client.get("/api/experiments").json() == []
    beat = client.post("/agent/heartbeat", json={"job_id": running["job_id"]}, headers=bearer(token))
    assert beat.json()["cancel"] is True  # the agent is told to stop
    late = client.post(
        "/agent/result", json={"job_id": running["job_id"], "ok": True, "result": RESULT}, headers=bearer(token)
    )
    assert late.status_code == 200 and client.get("/api/runs").json() == []  # nothing comes back to life
    assert client.post("/agent/claim", headers=bearer(token)).status_code == 204  # the waiting run was cancelled too


def test_what_each_run_found_in_a_picture_can_be_inspected(client: TestClient, tmp_path: Path) -> None:
    device_id, token = enrolled(client)
    e = start(client, tmp_path, device_id)
    first = client.post("/agent/claim", headers=bearer(token)).json()
    seen = {"min_confidence": 0.25, "pictures": {"0": [[0.1, 0.2, 0.5, 0.6, 0.91, 1]], "1": []}}
    client.post(
        "/agent/result",
        json={"job_id": first["job_id"], "ok": True, "result": {**RESULT, "predictions": seen}},
        headers=bearer(token),
    )
    done = client.get(f"/api/runs/{e['runs'][0]['id']}").json()
    assert (
        "predictions" not in done["result"] and len(done["result"]["predictions_sha"]) == 64
    )  # kept as a file, not in the row

    one = client.get(f"/api/experiments/{e['id']}/inspect?image=0").json()
    assert one["image"] == 0 and len(one["runs"]) == 2
    by_label = {r["variant_label"]: r for r in one["runs"]}
    assert by_label["ONNX FP32"]["detections"] == [[0.1, 0.2, 0.5, 0.6, 0.91, 1]]
    assert by_label["ONNX FP32"]["class_names"] == ["chips", "biscuit", "chocolate"]
    assert by_label["PyTorch (.pt) baseline"]["detections"] is None  # that run has not reported (yet)
    assert client.get(f"/api/experiments/{e['id']}/inspect?image=1").json()["runs"][0]["detections"] == []
    assert client.get(f"/api/experiments/{e['id']}/inspect?image=7").json()["runs"][0]["detections"] is None
    assert client.get("/api/experiments/999/inspect?image=0").status_code == 404
