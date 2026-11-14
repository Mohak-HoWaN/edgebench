"""The agent source package a Pi installs from the server."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

from fastapi.testclient import TestClient

from edgebench import package
from edgebench.config import Settings
from edgebench.main import create_app

AGENT = Path(__file__).resolve().parents[2] / "agent"


def test_the_package_holds_the_agent_and_is_the_same_every_time() -> None:
    first, second = package.build(AGENT), package.build(AGENT)
    assert first is not None and first == second
    name, data = first
    assert name.startswith("edgebench_agent-") and name.endswith(".tar.gz")
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        members = tar.getnames()
    root = name.removesuffix(".tar.gz")
    assert f"{root}/pyproject.toml" in members and f"{root}/edgebench_agent/agent.py" in members
    assert not any("__pycache__" in m or "tests" in m for m in members)


def test_no_agent_source_means_no_package(tmp_path: Path) -> None:
    assert package.build(tmp_path) is None


def test_the_server_hands_it_out_and_the_enrolment_names_its_address(client: TestClient) -> None:
    enrolment = client.post("/api/devices", json={"name": "Bench Pi", "expected_kind": "pi"}).json()
    url = enrolment["package_url"]
    assert url == f"http://testserver/agent/package/{url.rsplit('/', 1)[1]}"
    got = client.get(f"/agent/package/{url.rsplit('/', 1)[1]}")
    assert got.status_code == 200 and got.content[:2] == b"\x1f\x8b"  # gzip
    assert client.get("/agent/package/other.tar.gz").status_code == 404


def test_a_configured_public_address_replaces_the_one_the_browser_used(settings: Settings) -> None:
    configured = settings.model_copy(update={"public_url": "http://100.64.0.7:8000/"})
    with TestClient(create_app(configured)) as c:
        out = c.post("/api/devices", json={"name": "Pi", "expected_kind": "pi"}).json()
    assert out["server_url"] == "http://100.64.0.7:8000" and out["package_url"].startswith(
        "http://100.64.0.7:8000/agent/package/"
    )
