from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from edgebench import api_agent
from edgebench.config import Settings
from edgebench.db import make_engine, migrate
from edgebench.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        worker_poll_seconds=0.05,
        heartbeat_seconds=0.1,
        stale_seconds=5,
        allowed_hosts=["testserver", "localhost"],  # TestClient talks to http://testserver
        _env_file=None,
    )


@pytest.fixture
def engine(settings: Settings) -> Iterator[Engine]:
    migrate(settings.db_path)
    eng = make_engine(settings.db_path)
    yield eng
    eng.dispose()


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture(autouse=True)
def short_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    """An agent's claim waits for a job; in tests an empty queue must answer in a fraction of a second, not 25 s."""
    monkeypatch.setattr(api_agent, "LONG_POLL_SECONDS", 0.3)
    monkeypatch.setattr(api_agent, "POLL_EVERY", 0.05)
