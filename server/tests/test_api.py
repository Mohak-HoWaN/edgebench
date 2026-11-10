from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from starlette.websockets import WebSocketDisconnect

from edgebench import __version__, queue
from edgebench.config import Settings
from edgebench.db import downgrade, make_engine, migrate
from edgebench.events import EventHub
from edgebench.logs import JsonFormatter
from edgebench.main import create_app


def test_health_reports_database_queue_and_worker(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["version"] == __version__
    assert body["db"] == {"ok": True, "journal_mode": "wal", "error": None}
    assert body["queue"]["queued"] == 0 and body["worker_running"] is True
    assert body["disk_free_gb"] > 0


def test_health_counts_queued_jobs(settings: Settings) -> None:
    settings = settings.model_copy(update={"worker_enabled": False})
    with TestClient(create_app(settings)) as c:
        queue.enqueue(c.app.state.engine, "t")  # type: ignore[attr-defined]
        body = c.get("/api/health").json()
    assert body["queue"]["queued"] == 1 and body["worker_running"] is False and body["status"] == "ok"


def test_health_degrades_instead_of_failing_when_the_database_breaks(client: TestClient, tmp_path: Path) -> None:
    unreachable = create_engine(f"sqlite:///{(tmp_path / 'no-such-folder' / 'x.db').as_posix()}")
    client.app.state.engine = unreachable  # type: ignore[attr-defined]
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "degraded"
    assert r.json()["db"]["ok"] is False and r.json()["queue"] == {}


def test_websocket_says_hello_then_relays_published_events(client: TestClient) -> None:
    with client.websocket_connect("/ws/events") as ws:
        assert ws.receive_json() == {"type": "hello", "version": __version__}
        client.app.state.hub.publish({"type": "job.state", "id": 1, "state": "done"})  # type: ignore[attr-defined]
        assert ws.receive_json() == {"type": "job.state", "id": 1, "state": "done"}


def test_publishing_after_the_event_loop_closed_never_raises_into_the_worker() -> None:
    hub = EventHub()
    loop = asyncio.new_event_loop()
    hub.bind(loop)
    loop.close()
    hub.publish({"type": "job.state"})  # shutdown race: must be swallowed


def test_requests_for_an_unknown_host_name_are_refused(client: TestClient) -> None:
    """A DNS-rebinding page reaches the server under its own host name; that must not be answered."""
    assert client.get("/api/health", headers={"host": "evil.example"}).status_code == 400
    assert client.get("/api/health", headers={"host": "localhost:8000"}).status_code == 200


def test_websocket_refuses_a_page_from_another_origin(client: TestClient) -> None:
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        client.websocket_connect("/ws/events", headers={"origin": "http://evil.example"}),
    ):
        pass
    assert exc.value.code == 1008


def test_websocket_accepts_the_apps_own_origin(client: TestClient) -> None:
    with client.websocket_connect("/ws/events", headers={"origin": "http://testserver"}) as ws:
        assert ws.receive_json()["type"] == "hello"


def test_migrations_create_every_table_and_index_and_can_be_reversed(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    migrate(db)
    insp = inspect(make_engine(db))
    assert {"jobs", "artifacts", "models", "datasets", "devices", "experiments", "runs"} <= set(insp.get_table_names())
    assert "ix_jobs_claim" in {i["name"] for i in insp.get_indexes("jobs")}
    assert "ix_runs_experiment_id" in {i["name"] for i in insp.get_indexes("runs")}
    assert "ix_runs_device_id" in {i["name"] for i in insp.get_indexes("runs")}
    downgrade(db, "base")
    assert set(inspect(make_engine(db)).get_table_names()) <= {"alembic_version"}
    migrate(db)  # and forward again
    assert "jobs" in inspect(make_engine(db)).get_table_names()


def _spa(tmp_path: Path, settings: Settings) -> TestClient:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("do not serve")
    return TestClient(create_app(settings.model_copy(update={"web_dist": dist})))


def test_spa_serves_files_and_falls_back_to_index_for_client_routes(tmp_path: Path, settings: Settings) -> None:
    with _spa(tmp_path, settings) as c:
        assert c.get("/").text == "<html>app</html>"
        assert c.get("/models").text == "<html>app</html>"  # a client-side route, reloaded
        assert c.get("/assets/app.js").text == "console.log(1)"
        assert c.get("/api/health").json()["status"] == "ok"  # API routes are not shadowed


def test_spa_returns_404_for_a_missing_file_instead_of_the_html_shell(tmp_path: Path, settings: Settings) -> None:
    """An old tab asking for a chunk a rebuild renamed must not get HTML back as if it were JavaScript."""
    with _spa(tmp_path, settings) as c:
        assert c.get("/assets/Models-gone.js").status_code == 404
        assert c.get("/favicon.ico").status_code == 404
        assert c.get("/some/client/route").text == "<html>app</html>"  # a route, not a file: still the shell


def test_spa_does_not_swallow_unknown_api_paths_or_escape_the_folder(tmp_path: Path, settings: Settings) -> None:
    with _spa(tmp_path, settings) as c:
        assert c.get("/api/nope").status_code == 404
        assert c.get("/ws/nope").status_code == 404
        assert c.get("/api").status_code == 404  # bare prefixes too, not the HTML shell
        assert c.get("/ws").status_code == 404
        for attack in ("/../secret.txt", "/%2e%2e/secret.txt", "/..%2fsecret.txt", "/assets/../../secret.txt"):
            assert "do not serve" not in c.get(attack).text


def test_json_log_lines_carry_extra_fields_and_tracebacks() -> None:
    try:
        raise ValueError("bad")
    except ValueError:
        record = logging.LogRecord("edgebench.x", logging.ERROR, __file__, 1, "job %s failed", ("7",), sys.exc_info())
    record.job_id = 7
    out = json.loads(JsonFormatter().format(record))
    assert (
        out["message"] == "job 7 failed"
        and out["level"] == "ERROR"
        and out["job_id"] == 7
        and "ValueError" in out["exc"]
    )
