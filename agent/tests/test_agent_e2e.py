"""The real agent talking to the real server, with a stand-in for the benchmark process."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_agent_api import add_device, enrolled, seed_dataset, seed_model

from edgebench_agent.agent import Agent
from edgebench_agent.client import Rejected, ServerClient, sha256_file
from edgebench_agent.fingerprint import collect

TESTS = Path(__file__).parent


@pytest.fixture(autouse=True)
def fake_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PYTHONPATH", str(TESTS))
    monkeypatch.setenv("FAKE_BENCH_PIDS", str(tmp_path / "pids.txt"))
    monkeypatch.delenv("FAKE_BENCH", raising=False)


def make_agent(server: TestClient, tmp_path: Path, token: str) -> Agent:
    client = ServerClient("", token=token, http=server)
    return Agent(client, tmp_path / "agent-state", heartbeat_seconds=0.2, bench_module="fake_bench")


def queue_run(server: TestClient, tmp_path: Path, device_id: int, baseline: bool = False) -> dict[str, Any]:
    model_id, variant_id = seed_model(server, tmp_path / "seed")
    dataset_id = seed_dataset(server, tmp_path / "seed")
    body = {
        "model_id": model_id,
        "variant_id": None if baseline else variant_id,
        "dataset_id": dataset_id,
        "device_id": device_id,
        "params": {"threads": 2, "warmup": 1, "iterations": 5},
    }
    r = server.post("/api/runs", json=body)
    assert r.status_code == 201, r.text
    return dict(r.json())


def status(server: TestClient, run_id: int) -> dict[str, Any]:
    return dict(server.get(f"/api/runs/{run_id}").json())


def test_the_agent_enrols_remembers_who_it_is_and_reports_its_hardware(server: TestClient, tmp_path: Path) -> None:
    created = add_device(server, "bench PC")
    agent = make_agent(server, tmp_path, token="")
    agent.client.token = None
    data = agent.enroll(created["enroll_token"])
    assert data["kind"] == "pc" and agent.client.token == data["device_token"]
    fresh = make_agent(server, tmp_path, token="")
    fresh.client.token = None
    assert fresh.load_identity() and fresh.client.token == data["device_token"]  # a restart needs no token
    device = server.get("/api/devices").json()[0]
    assert device["agent_version"] == "0.1.0" and device["fingerprint"]["logical_cores"]
    assert {"os", "cpu", "python", "bits", "packages", "ram_bytes"} <= collect().keys()


def test_a_job_runs_end_to_end_and_the_result_reaches_the_app(server: TestClient, tmp_path: Path) -> None:
    device_id, token = enrolled(server)
    run = queue_run(server, tmp_path, device_id)
    agent = make_agent(server, tmp_path, token)
    agent.serve(once=True)
    got = status(server, run["id"])
    assert got["status"] == "done" and got["result"]["speed"]["stages"]["total"]["p50"] == 9.5
    assert got["result"]["runtime"] == {"kind": "onnx", "threads": 2}  # the settings reached the child
    cache = tmp_path / "agent-state" / "cache"
    assert any((cache / "bundles").glob("*/model.onnx")) and any((cache / "datasets").glob("*/data.json"))


def test_the_second_run_downloads_nothing_it_already_has(
    server: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device_id, token = enrolled(server)
    agent = make_agent(server, tmp_path, token)
    downloads: list[str] = []
    original = agent.client.download

    def counting(sha: str, name: str | None, dest: Path, stop: Any = lambda: False) -> None:
        downloads.append(f"{sha[:8]}/{name}")
        original(sha, name, dest, stop)

    monkeypatch.setattr(agent.client, "download", counting)
    queue_run(server, tmp_path, device_id)
    agent.serve(once=True)
    first = list(downloads)
    assert len(first) == 2  # the model file and the dataset
    queue_run(server, tmp_path, device_id)
    agent.serve(once=True)
    assert downloads == first  # a cache hit costs no transfer


def test_a_baseline_run_gets_the_checkpoint_under_a_name_ultralytics_understands(
    server: TestClient, tmp_path: Path
) -> None:
    device_id, token = enrolled(server)
    queue_run(server, tmp_path, device_id, baseline=True)
    make_agent(server, tmp_path, token).serve(once=True)
    cached = list((tmp_path / "agent-state" / "cache" / "files").glob("*/model.pt"))
    assert len(cached) == 1 and cached[0].read_bytes() == b"pretend checkpoint"


def test_a_crashing_benchmark_fails_one_run_and_the_agent_carries_on(
    server: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device_id, token = enrolled(server)
    agent = make_agent(server, tmp_path, token)
    crashed = queue_run(server, tmp_path, device_id)
    monkeypatch.setenv("FAKE_BENCH", "crash")
    agent.serve(once=True)
    got = status(server, crashed["id"])
    assert got["status"] == "failed" and "stopped unexpectedly (exit code 7)" in got["error"]
    assert "about to crash" in got["result"]["log"]
    monkeypatch.setenv("FAKE_BENCH", "ok")
    after = queue_run(server, tmp_path, device_id)
    agent.serve(once=True)
    assert status(server, after["id"])["status"] == "done"


def test_a_missing_runtime_is_reported_as_not_available(
    server: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device_id, token = enrolled(server)
    run = queue_run(server, tmp_path, device_id)
    monkeypatch.setenv("FAKE_BENCH", "unavailable")
    make_agent(server, tmp_path, token).serve(once=True)
    got = status(server, run["id"])
    assert got["status"] == "unavailable" and "ncnn is not installed" in got["error"]


def test_cancelling_a_running_job_stops_the_benchmark_process(
    server: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import psutil

    device_id, token = enrolled(server)
    run = queue_run(server, tmp_path, device_id)
    monkeypatch.setenv("FAKE_BENCH", "slow")
    agent = make_agent(server, tmp_path, token)
    worker = threading.Thread(target=lambda: agent.serve(once=True), daemon=True)
    worker.start()
    pids = tmp_path / "pids.txt"
    deadline = time.monotonic() + 20
    while not (pids.exists() and pids.read_text().strip()) and time.monotonic() < deadline:
        time.sleep(0.05)
    child = int(pids.read_text().split()[0])
    assert psutil.pid_exists(child)
    assert server.post(f"/api/runs/{run['id']}/cancel").status_code == 200
    worker.join(timeout=20)
    assert not worker.is_alive()
    assert status(server, run["id"])["status"] == "cancelled"
    time.sleep(0.3)
    assert not psutil.pid_exists(child)  # the process was killed, not left running


def test_a_revoked_agent_learns_it_has_been_cut_off(server: TestClient, tmp_path: Path) -> None:
    device_id, token = enrolled(server)
    server.delete(f"/api/devices/{device_id}")
    with pytest.raises(Rejected):
        make_agent(server, tmp_path, token).serve(once=True)


def test_an_interrupted_download_resumes_and_a_corrupt_one_is_thrown_away(server: TestClient, tmp_path: Path) -> None:
    device_id, token = enrolled(server)
    queue_run(server, tmp_path, device_id, baseline=True)
    spec = server.post("/agent/claim", headers={"authorization": f"Bearer {token}"}).json()
    sha = spec["artifact"]["sha256"]
    client = ServerClient("", token=token, http=server)

    dest = tmp_path / "dl" / "model.pt"
    dest.parent.mkdir()
    dest.with_name("model.pt.part").write_bytes(b"pretend ")  # the first 8 bytes arrived before the connection dropped
    client.download(sha, None, dest)
    assert dest.read_bytes() == b"pretend checkpoint" and sha256_file(dest) == sha

    other = tmp_path / "dl" / "other.pt"
    other.with_name("other.pt.part").write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="checksum"):
        client.download(sha, None, other)
    assert not other.exists() and not other.with_name("other.pt.part").exists()


def test_the_command_line_refuses_to_start_unenrolled(tmp_path: Path) -> None:
    from edgebench_agent.__main__ import main

    assert main(["--server", "http://127.0.0.1:9", "--state-dir", str(tmp_path / "none")]) == 2
    assert sys.version_info >= (3, 11)


def test_an_unreachable_server_at_the_end_of_a_run_does_not_take_the_agent_down(
    server: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    device_id, token = enrolled(server)
    run = queue_run(server, tmp_path, device_id)
    agent = make_agent(server, tmp_path, token)

    def unreachable(*_: Any, **__: Any) -> None:
        raise httpx.ConnectError("the server went away")

    monkeypatch.setattr(agent.client, "result", unreachable)
    agent.serve(once=True)  # returns normally instead of raising
    assert status(server, run["id"])["status"] == "running"  # the server never heard; its stale sweep will mark it lost


def test_a_restarted_agent_reports_what_it_runs_on_now_not_what_it_had_at_enrolment(
    server: TestClient, tmp_path: Path
) -> None:
    device_id, token = enrolled(server)  # enrolled with a stand-in fingerprint that has no packages
    assert "packages" not in server.get("/api/devices").json()[0]["fingerprint"]
    queue_run(server, tmp_path, device_id)
    make_agent(server, tmp_path, token).serve(once=True)
    now = server.get("/api/devices").json()[0]["fingerprint"]
    assert now["python"] == collect()["python"] and "packages" in now
