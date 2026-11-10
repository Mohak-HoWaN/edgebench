"""The agent protocol (ADR 0003) and the run lifecycle, driven with plain HTTP calls."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from helpers import commit_files, make_dataset, make_stale, wait_version
from sqlmodel import Session
from test_dataset_import import yolo_folder
from test_datasets_api import jpeg, new_dataset

from edgebench import api_agent, queue
from edgebench.artifacts import sha256_file
from edgebench.devices import ONLINE_WITHIN
from edgebench.model_jobs import register_artifact
from edgebench.models import Device, MlModel, Variant, utcnow

FINGERPRINT_PC = {"hostname": "desk", "os": "Windows 11", "machine": "AMD64", "pi_model": None}
FINGERPRINT_PI = {"hostname": "pi", "os": "Linux", "machine": "aarch64", "pi_model": "Raspberry Pi 5 Model B"}


@pytest.fixture(autouse=True)
def short_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_agent, "LONG_POLL_SECONDS", 0.3)
    monkeypatch.setattr(api_agent, "POLL_EVERY", 0.05)


def bearer(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


def add_device(c: TestClient, name: str = "this PC", expected: str | None = "pc") -> dict[str, Any]:
    r = c.post("/api/devices", json={"name": name, "expected_kind": expected})
    assert r.status_code == 201
    return dict(r.json())


def enrolled(c: TestClient, name: str = "this PC", fingerprint: dict[str, Any] | None = None) -> tuple[int, str]:
    created = add_device(c, name)
    r = c.post("/agent/enroll", json={"token": created["enroll_token"], "fingerprint": fingerprint or FINGERPRINT_PC})
    assert r.status_code == 200, r.text
    return r.json()["device_id"], r.json()["device_token"]


def seed_model(c: TestClient, tmp_path: Path) -> tuple[int, int]:
    """A ready model with one finished ONNX conversion, backed by real files in the store (made once per client)."""
    cached: tuple[int, int] | None = getattr(c, "seeded_model", None)
    if cached is not None:
        return cached
    s = c.app.state.services  # type: ignore[attr-defined]
    tmp_path.mkdir(parents=True, exist_ok=True)
    pt = tmp_path / "up.pt"
    pt.write_bytes(b"pretend checkpoint")
    sha = sha256_file(pt)
    s.store.put_file(pt, sha)
    work = s.store.new_workdir()
    (work / "model.onnx").write_bytes(b"pretend onnx")
    bundle, size = s.store.put_directory(work)
    with Session(s.engine) as session:
        register_artifact(session, sha, "model", 18)
        register_artifact(session, bundle, "bundle", size)
        m = MlModel(
            name="retail", artifact_sha256=sha, status="ready", imgsz=640, class_names=["chips", "biscuit", "chocolate"]
        )
        session.add(m)
        session.commit()
        session.refresh(m)
        assert m.id is not None
        v = Variant(
            model_id=m.id, op="onnx_fp32", format="ONNX", precision="FP32", imgsz=640, state="ready",
            artifact_sha256=bundle, main_file="model.onnx", size_bytes=size, cache_key="k",
        )  # fmt: skip
        session.add(v)
        session.commit()
        session.refresh(v)
        assert m.id and v.id
        c.seeded_model = (m.id, v.id)  # type: ignore[attr-defined]
        return m.id, v.id


def seed_dataset(c: TestClient, tmp_path: Path) -> int:
    cached: int | None = getattr(c, "seeded_dataset", None)
    if cached is None:
        cached = int(make_dataset(c, yolo_folder(tmp_path / "ds"))["id"])
        c.seeded_dataset = cached  # type: ignore[attr-defined]
    return cached


def start_run(c: TestClient, tmp_path: Path, device_id: int, baseline: bool = False) -> dict[str, Any]:
    model_id, variant_id = seed_model(c, tmp_path)
    dataset_id = seed_dataset(c, tmp_path)
    body = {
        "model_id": model_id,
        "variant_id": None if baseline else variant_id,
        "dataset_id": dataset_id,
        "device_id": device_id,
        "params": {"threads": 2, "warmup": 1, "iterations": 5},
    }
    r = c.post("/api/runs", json=body)
    assert r.status_code == 201, r.text
    return dict(r.json())


# --- enrolment ----------------------------------------------------------------------------------------------------


def test_a_device_enrols_once_with_a_token_and_its_type_comes_from_its_fingerprint(client: TestClient) -> None:
    created = add_device(client, "bench Pi", expected="pc")  # the person said PC; the machine says otherwise
    assert created["device"]["enrolled"] is False and created["expires_minutes"] == 60
    r = client.post("/agent/enroll", json={"token": created["enroll_token"], "fingerprint": FINGERPRINT_PI})
    assert r.status_code == 200 and r.json()["kind"] == "pi"
    device = client.get("/api/devices").json()[0]
    assert device["enrolled"] and device["kind"] == "pi" and device["expected_kind"] == "pc"  # the mismatch is visible
    assert device["fingerprint"]["pi_model"] == "Raspberry Pi 5 Model B"
    again = client.post("/agent/enroll", json={"token": created["enroll_token"], "fingerprint": FINGERPRINT_PI})
    assert again.status_code == 401  # a token works once


def test_a_wrong_or_expired_enrolment_token_is_refused(client: TestClient) -> None:
    assert client.post("/agent/enroll", json={"token": "nope", "fingerprint": {}}).status_code == 401
    created = add_device(client)
    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        d = session.get(Device, created["device"]["id"])
        assert d is not None
        d.enroll_expires_at = utcnow() - timedelta(minutes=1)
        session.add(d)
        session.commit()
    r = client.post("/agent/enroll", json={"token": created["enroll_token"], "fingerprint": {}})
    assert r.status_code == 401 and "expired" in r.json()["detail"]


def test_the_stored_tokens_are_hashes(client: TestClient, settings: Any) -> None:
    created = add_device(client)
    device_id, token = enrolled(client, "second")
    rows = sqlite3.connect(settings.db_path).execute("select token_hash, enroll_hash from devices").fetchall()
    flat = {v for row in rows for v in row if v}
    assert created["enroll_token"] not in flat and token not in flat and device_id


def test_agent_routes_need_a_valid_device_token(client: TestClient) -> None:
    calls: list[Callable[[dict[str, str]], Any]] = [
        lambda h: client.post("/agent/claim", headers=h),
        lambda h: client.post("/agent/heartbeat", json={}, headers=h),
        lambda h: client.get("/agent/artifacts/" + "0" * 64, headers=h),
    ]
    for call in calls:
        assert call({}).status_code == 401
        assert call(bearer("eb-device-wrong")).status_code == 401


def test_a_revoked_device_is_cut_off_at_once(client: TestClient) -> None:
    device_id, token = enrolled(client)
    assert client.post("/agent/claim", headers=bearer(token)).status_code == 204
    assert client.delete(f"/api/devices/{device_id}").status_code == 204
    assert client.post("/agent/claim", headers=bearer(token)).status_code == 401
    assert client.get("/api/devices").json() == []


def test_a_new_token_replaces_the_old_one(client: TestClient) -> None:
    device_id, old = enrolled(client)
    fresh = client.post(f"/api/devices/{device_id}/enroll-token").json()
    assert client.post("/agent/claim", headers=bearer(old)).status_code == 401
    r = client.post("/agent/enroll", json={"token": fresh["enroll_token"], "fingerprint": FINGERPRINT_PC})
    assert (
        r.status_code == 200
        and client.post("/agent/claim", headers=bearer(r.json()["device_token"])).status_code == 204
    )


def test_a_device_is_online_only_while_it_keeps_talking(client: TestClient) -> None:
    device_id, token = enrolled(client)
    assert client.get("/api/devices").json()[0]["online"] is True  # enrolling counts as contact
    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        d = session.get(Device, device_id)
        assert d is not None
        d.last_seen_at = utcnow() - ONLINE_WITHIN - timedelta(seconds=1)
        session.add(d)
        session.commit()
    assert client.get("/api/devices").json()[0]["online"] is False
    client.post("/agent/heartbeat", json={}, headers=bearer(token))
    assert client.get("/api/devices").json()[0]["online"] is True


# --- runs -----------------------------------------------------------------------------------------------------------


def test_a_run_is_created_claimed_with_a_complete_spec_and_finished(client: TestClient, tmp_path: Path) -> None:
    device_id, token = enrolled(client)
    run = start_run(client, tmp_path, device_id)
    assert run["status"] == "queued" and run["variant_label"] == "ONNX FP32" and run["runtime"] == "onnx"

    claimed = client.post("/agent/claim", headers=bearer(token))
    assert claimed.status_code == 200
    spec = claimed.json()
    assert spec["run_id"] == run["id"] and spec["kind"] == "onnx" and spec["imgsz"] == 640
    assert spec["model_names"] == ["chips", "biscuit", "chocolate"] and spec["params"]["iterations"] == 5
    assert spec["artifact"]["layout"] == "bundle" and spec["artifact"]["files"] == ["model.onnx"]
    assert spec["dataset"]["names_generic"] is False
    assert client.get(f"/api/runs/{run['id']}").json()["status"] == "running"
    assert client.post("/agent/claim", headers=bearer(token)).status_code == 204  # nothing else waiting

    beat = client.post(
        "/agent/heartbeat",
        json={"job_id": spec["job_id"], "fraction": 0.4, "message": "Running"},
        headers=bearer(token),
    )
    assert beat.json() == {"ok": True, "cancel": False}
    assert client.get(f"/api/runs/{run['id']}").json()["progress"] == 0.4

    result = {"speed": {"stages": {"total": {"p50": 12.5}}}, "accuracy": {"available": False}}
    done = client.post(
        "/agent/result",
        json={"job_id": spec["job_id"], "ok": True, "result": result, "log": "fine"},
        headers=bearer(token),
    )
    assert done.json() == {"accepted": True}
    final = client.get(f"/api/runs/{run['id']}").json()
    assert final["status"] == "done" and final["result"]["speed"]["stages"]["total"]["p50"] == 12.5
    assert final["result"]["log"] == "fine" and final["finished_at"] and final["progress"] is None


def test_a_baseline_run_names_the_checkpoint_itself(client: TestClient, tmp_path: Path) -> None:
    device_id, token = enrolled(client)
    run = start_run(client, tmp_path, device_id, baseline=True)
    assert run["variant_label"] == "PyTorch (.pt) baseline" and run["runtime"] == "pytorch"
    spec = client.post("/agent/claim", headers=bearer(token)).json()
    assert spec["artifact"] == {"layout": "file", "sha256": spec["artifact"]["sha256"], "main": "model.pt"}


def test_runs_are_refused_for_things_that_are_not_ready(client: TestClient, tmp_path: Path) -> None:
    device_id, _ = enrolled(client)
    model_id, variant_id = seed_model(client, tmp_path)
    dataset_id = seed_dataset(client, tmp_path)
    ok = {"model_id": model_id, "variant_id": variant_id, "dataset_id": dataset_id, "device_id": device_id}
    assert client.post("/api/runs", json={**ok, "model_id": 999}).status_code == 422
    assert client.post("/api/runs", json={**ok, "variant_id": 999}).status_code == 422
    assert client.post("/api/runs", json={**ok, "dataset_id": 999}).status_code == 422
    waiting = add_device(client, "not connected yet")["device"]["id"]
    refused = client.post("/api/runs", json={**ok, "device_id": waiting})
    assert refused.status_code == 422 and "agent" in refused.json()["detail"]
    assert client.post("/api/runs", json={**ok, "params": {"threads": 0}}).status_code == 422
    with Session(client.app.state.engine) as session:  # type: ignore[attr-defined]
        v = session.get(Variant, variant_id)
        assert v is not None
        v.state = "failed"
        session.add(v)
        session.commit()
    assert "not finished" in client.post("/api/runs", json=ok).json()["detail"]


def test_a_device_only_gets_its_own_jobs(client: TestClient, tmp_path: Path) -> None:
    first, token_a = enrolled(client, "A")
    _, token_b = enrolled(client, "B")
    run = start_run(client, tmp_path, first)
    assert client.post("/agent/claim", headers=bearer(token_b)).status_code == 204
    spec = client.post("/agent/claim", headers=bearer(token_a)).json()
    assert spec["run_id"] == run["id"]
    # B cannot report on, or keep alive, A's job
    assert client.post("/agent/heartbeat", json={"job_id": spec["job_id"]}, headers=bearer(token_b)).status_code == 404
    assert (
        client.post("/agent/result", json={"job_id": spec["job_id"], "ok": True}, headers=bearer(token_b)).status_code
        == 404
    )


def test_cancelling_a_waiting_run_is_immediate_and_a_running_one_is_asked_to_stop(
    client: TestClient, tmp_path: Path
) -> None:
    device_id, token = enrolled(client)
    waiting = start_run(client, tmp_path / "a", device_id)
    assert client.post(f"/api/runs/{waiting['id']}/cancel").json()["status"] == "cancelled"
    assert client.post("/agent/claim", headers=bearer(token)).status_code == 204

    running = start_run(client, tmp_path / "b", device_id)
    spec = client.post("/agent/claim", headers=bearer(token)).json()
    assert client.post(f"/api/runs/{running['id']}/cancel").json()["status"] == "running"  # asked, not yet stopped
    beat = client.post("/agent/heartbeat", json={"job_id": spec["job_id"]}, headers=bearer(token))
    assert beat.json()["cancel"] is True
    client.post(
        "/agent/result", json={"job_id": spec["job_id"], "ok": False, "kind": "cancelled"}, headers=bearer(token)
    )
    assert client.get(f"/api/runs/{running['id']}").json()["status"] == "cancelled"
    assert client.post(f"/api/runs/{running['id']}/cancel").status_code == 409


def test_a_failed_or_unavailable_run_keeps_the_reason(client: TestClient, tmp_path: Path) -> None:
    device_id, token = enrolled(client)
    for kind, status in (("failed", "failed"), ("unavailable", "unavailable")):
        run = start_run(client, tmp_path / kind, device_id)
        spec = client.post("/agent/claim", headers=bearer(token)).json()
        client.post(
            "/agent/result",
            json={"job_id": spec["job_id"], "ok": False, "kind": kind, "error": "ncnn is not installed", "log": "tb"},
            headers=bearer(token),
        )
        got = client.get(f"/api/runs/{run['id']}").json()
        assert got["status"] == status and got["error"] == "ncnn is not installed" and got["result"] == {"log": "tb"}


def test_an_agent_that_vanishes_leaves_the_run_lost_not_stuck_and_a_late_result_is_ignored(
    client: TestClient, tmp_path: Path
) -> None:
    device_id, token = enrolled(client)
    run = start_run(client, tmp_path, device_id)
    spec = client.post("/agent/claim", headers=bearer(token)).json()
    engine = client.app.state.engine  # type: ignore[attr-defined]
    make_stale(engine, spec["job_id"])
    assert queue.requeue_stale(engine, 30) == 1  # the server's worker does this every few seconds
    assert client.get(f"/api/runs/{run['id']}").json()["status"] == "lost"
    late = client.post(
        "/agent/result", json={"job_id": spec["job_id"], "ok": True, "result": {}}, headers=bearer(token)
    )
    assert late.json() == {"accepted": False}
    assert client.get(f"/api/runs/{run['id']}").json()["status"] == "lost"
    beat = client.post("/agent/heartbeat", json={"job_id": spec["job_id"]}, headers=bearer(token))
    assert beat.json()["lost"] is True  # an agent that comes back is told to stop


def test_run_again_repeats_the_same_measurement(client: TestClient, tmp_path: Path) -> None:
    device_id, _ = enrolled(client)
    run = start_run(client, tmp_path, device_id)
    again = client.post(f"/api/runs/{run['id']}/again").json()
    assert again["id"] != run["id"] and again["params"] == run["params"] and again["dataset_id"] == run["dataset_id"]
    assert [r["id"] for r in client.get("/api/runs").json()] == [again["id"], run["id"]]


def test_a_run_records_which_version_of_the_dataset_it_used_and_a_newer_version_does_not_change_it(
    client: TestClient, tmp_path: Path
) -> None:
    device_id, token = enrolled(client)
    model_id, variant_id = seed_model(client, tmp_path)
    dataset = new_dataset(client, "growing")
    commit_files(client, dataset, {"a.jpg": jpeg((200, 10, 10)), "b.jpg": jpeg((10, 200, 10))})
    wait_version(client, dataset)
    body = {"model_id": model_id, "variant_id": variant_id, "dataset_id": dataset, "device_id": device_id}
    first = client.post("/api/runs", json=body).json()
    assert first["dataset_version"] == 1 and first["dataset_name"] == "growing"

    commit_files(client, dataset, {"c.jpg": jpeg((10, 10, 200))})
    wait_version(client, dataset, "2")
    second = client.post("/api/runs", json=body).json()  # no version given: the newest
    pinned = client.post("/api/runs", json={**body, "dataset_version": 1}).json()  # or one you choose
    assert (second["dataset_version"], pinned["dataset_version"]) == (2, 1)
    assert client.get(f"/api/runs/{first['id']}").json()["dataset_version"] == 1  # unchanged by the newer version
    spec = client.post("/agent/claim", headers=bearer(token)).json()
    assert spec["run_id"] == first["id"]  # the agent is told which pictures: version 1's
    assert client.post("/api/runs", json={**body, "dataset_version": 9}).status_code == 422
    assert client.post("/api/runs", json={**body, "dataset_id": 999}).status_code == 422


def test_a_dataset_version_that_is_still_building_cannot_be_run(client: TestClient, tmp_path: Path) -> None:
    device_id, _ = enrolled(client)
    model_id, variant_id = seed_model(client, tmp_path)
    dataset = new_dataset(client, "empty")
    r = client.post(
        "/api/runs",
        json={"model_id": model_id, "variant_id": variant_id, "dataset_id": dataset, "device_id": device_id},
    )
    assert r.status_code == 422 and "not ready" in r.json()["detail"]


def test_threads_and_cpus_cannot_go_beyond_what_the_device_has(client: TestClient, tmp_path: Path) -> None:
    created = add_device(client, "eight threads")
    client.post(
        "/agent/enroll",
        json={
            "token": created["enroll_token"],
            "fingerprint": {**FINGERPRINT_PC, "logical_cores": 8, "physical_cores": 4},
        },
    )
    model_id, variant_id = seed_model(client, tmp_path)
    dataset_id = seed_dataset(client, tmp_path)
    ok = {
        "model_id": model_id,
        "variant_id": variant_id,
        "dataset_id": dataset_id,
        "device_id": created["device"]["id"],
    }

    def run(**params: object) -> object:
        return client.post("/api/runs", json={**ok, "params": params})

    too_many = run(threads=9)
    assert too_many.status_code == 422 and "can run 8 threads" in too_many.json()["detail"]  # type: ignore[attr-defined]
    assert run(threads=8).status_code == 201  # type: ignore[attr-defined]
    assert "CPUs 0 to 7" in run(threads=1, cpu_list=[8]).json()["detail"]  # type: ignore[attr-defined]
    assert "twice" in run(threads=1, cpu_list=[1, 1]).json()["detail"]  # type: ignore[attr-defined]
    fewer = run(threads=3, cpu_list=[0, 1])  # pinned to two CPUs, three threads would fight over them
    assert fewer.status_code == 422 and "can run 2 threads" in fewer.json()["detail"]  # type: ignore[attr-defined]
    ok_pinned = run(threads=2, cpu_list=[0, 1])
    assert ok_pinned.status_code == 201 and ok_pinned.json()["params"]["cpu_list"] == [0, 1]  # type: ignore[attr-defined]


# --- files ----------------------------------------------------------------------------------------------------------


def test_artifacts_download_whole_or_resumed_and_refuse_odd_names(client: TestClient, tmp_path: Path) -> None:
    device_id, token = enrolled(client)
    run = start_run(client, tmp_path, device_id, baseline=True)
    spec = client.post("/agent/claim", headers=bearer(token)).json()
    sha = spec["artifact"]["sha256"]
    whole = client.get(f"/agent/artifacts/{sha}", headers=bearer(token))
    assert whole.status_code == 200 and whole.content == b"pretend checkpoint"
    part = client.get(f"/agent/artifacts/{sha}", headers={**bearer(token), "range": "bytes=8-"})
    assert part.status_code == 206 and part.content == b"checkpoint"
    bundle_sha = client.get(f"/api/variants/{run['variant_id'] or 1}/download").status_code  # the store is shared
    assert bundle_sha in (200, 404, 409)
    for bad in ("../../etc/passwd", "zz", "0" * 64):
        assert client.get(f"/agent/artifacts/{bad}", headers=bearer(token)).status_code == 404


def test_bundle_files_are_fetched_by_name_and_only_by_a_plain_name(client: TestClient, tmp_path: Path) -> None:
    device_id, token = enrolled(client)
    start_run(client, tmp_path, device_id)
    spec = client.post("/agent/claim", headers=bearer(token)).json()
    sha = spec["artifact"]["sha256"]
    got = client.get(f"/agent/artifacts/{sha}/model.onnx", headers=bearer(token))
    assert got.status_code == 200 and got.content == b"pretend onnx"
    assert client.get(f"/agent/artifacts/{sha}", headers=bearer(token)).status_code == 404  # a bundle is not one file
    assert client.get(f"/agent/artifacts/{sha}/nope.bin", headers=bearer(token)).status_code == 404
    assert client.get(f"/agent/artifacts/{sha}/..%2F..%2Fx", headers=bearer(token)).status_code == 404


def test_the_browser_side_is_protected_from_other_sites(client: TestClient, tmp_path: Path) -> None:
    hostile = {"origin": "https://evil.example"}
    assert client.post("/api/devices", json={"name": "x"}, headers=hostile).status_code == 403
    assert client.post("/api/runs", json={}, headers=hostile).status_code == 403
    assert client.post("/api/runs/1/cancel", headers=hostile).status_code == 403
    assert client.delete("/api/devices/1", headers=hostile).status_code == 403


def test_the_servers_own_worker_never_takes_a_benchmark(client: TestClient, tmp_path: Path) -> None:
    device_id, token = enrolled(client)
    start_run(client, tmp_path, device_id)
    time.sleep(0.4)  # the worker polls every 50 ms in tests
    assert client.post("/agent/claim", headers=bearer(token)).status_code == 200  # still there for the agent


def test_a_finished_run_can_be_removed_but_a_waiting_one_must_be_cancelled_first(
    client: TestClient, tmp_path: Path
) -> None:
    device_id, token = enrolled(client)
    waiting = start_run(client, tmp_path, device_id)
    refused = client.delete(f"/api/runs/{waiting['id']}")
    assert refused.status_code == 409 and "Cancel" in refused.json()["detail"]
    client.post(f"/api/runs/{waiting['id']}/cancel")
    assert client.delete(f"/api/runs/{waiting['id']}").status_code == 204
    assert client.get(f"/api/runs/{waiting['id']}").status_code == 404
    assert client.get("/api/runs").json() == []
    assert client.delete("/api/runs/999").status_code == 404
    assert client.delete("/api/runs/1", headers={"origin": "https://evil.example"}).status_code == 403
    assert token
