"""Fixtures for tests that run the real agent against the real server (in-process, over the server's test client)."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "server"), str(ROOT / "server" / "tests"), str(Path(__file__).parent)]

from edgebench import api_agent  # noqa: E402
from edgebench.config import Settings  # noqa: E402
from edgebench.main import create_app  # noqa: E402


@pytest.fixture
def server_settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "server-data",
        worker_poll_seconds=0.05,
        heartbeat_seconds=0.1,
        stale_seconds=5,
        allowed_hosts=["testserver", "localhost"],
        _env_file=None,
    )


@pytest.fixture
def server(server_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(api_agent, "LONG_POLL_SECONDS", 0.3)
    monkeypatch.setattr(api_agent, "POLL_EVERY", 0.05)
    with TestClient(create_app(server_settings)) as c:
        yield c
