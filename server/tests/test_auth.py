"""Owner login (ADR 0005): off until a password is set; then all but /agent and the pages needs the cookie."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from edgebench.auth import MIN_PASSWORD, Auth, Throttle, check_bind, hash_password, verify_password
from edgebench.config import Settings
from edgebench.main import create_app

PASSWORD = "correct horse battery"


@pytest.fixture
def locked(client: TestClient, settings: Settings) -> TestClient:
    client.app.state.auth.set_password(PASSWORD)  # type: ignore[attr-defined]
    return client


def test_nothing_is_asked_until_a_password_is_set(client: TestClient) -> None:
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/auth/status").json() == {"enabled": False, "signed_in": False}
    assert client.post("/api/auth/login", json={"password": "x"}).status_code == 409


def test_api_and_websocket_need_the_cookie_once_a_password_exists(locked: TestClient) -> None:
    assert locked.get("/api/health").status_code == 401
    assert locked.get("/api/models").status_code == 401
    with pytest.raises(WebSocketDisconnect), locked.websocket_connect("/ws/events"):
        pass
    assert locked.get("/api/auth/status").json() == {"enabled": True, "signed_in": False}


def test_wrong_password_is_refused_and_the_right_one_opens_a_session(locked: TestClient) -> None:
    assert locked.post("/api/auth/login", json={"password": "nope nope nope"}).status_code == 401
    ok = locked.post("/api/auth/login", json={"password": PASSWORD})
    assert ok.status_code == 200
    cookie = ok.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert locked.get("/api/health").status_code == 200
    with locked.websocket_connect("/ws/events") as ws:
        assert ws.receive_json()["type"] == "hello"
    locked.post("/api/auth/logout")
    assert locked.get("/api/health").status_code == 401


def test_cookie_is_secure_when_the_setting_says_so(settings: Settings) -> None:
    with TestClient(create_app(settings.model_copy(update={"secure_cookie": True}))) as c:
        c.app.state.auth.set_password(PASSWORD)  # type: ignore[attr-defined]
        assert "secure" in c.post("/api/auth/login", json={"password": PASSWORD}).headers["set-cookie"].lower()


def test_repeated_wrong_passwords_are_throttled(locked: TestClient) -> None:
    for _ in range(5):
        assert locked.post("/api/auth/login", json={"password": "wrong wrong wrong"}).status_code == 401
    refused = locked.post("/api/auth/login", json={"password": PASSWORD})  # even the right one waits
    assert refused.status_code == 429 and int(refused.headers["retry-after"]) > 0


def test_a_page_on_another_site_cannot_log_in_for_you(locked: TestClient) -> None:
    res = locked.post("/api/auth/login", json={"password": PASSWORD}, headers={"origin": "http://evil.example"})
    assert res.status_code == 403


def test_agent_routes_keep_their_own_tokens_and_the_pages_stay_public(locked: TestClient) -> None:
    assert locked.post("/agent/claim").status_code == 401  # a device token is required, not a session
    assert "Sign in first" not in locked.post("/agent/claim").text


def test_enrolment_guesses_are_throttled(client: TestClient) -> None:
    body = {"token": "eb-enroll-wrong", "fingerprint": {}}
    for _ in range(10):
        assert client.post("/agent/enroll", json=body).status_code == 401
    assert client.post("/agent/enroll", json=body).status_code == 429


def test_password_hashing_and_rules(tmp_path: Path) -> None:
    stored = hash_password(PASSWORD)
    assert verify_password(PASSWORD, stored) and not verify_password("other", stored)
    assert not verify_password(PASSWORD, "garbage")
    auth = Auth(tmp_path)
    with pytest.raises(ValueError, match=str(MIN_PASSWORD)):
        auth.set_password("short")


def test_throttle_forgives_after_the_window() -> None:
    now = [0.0]
    t = Throttle(limit=2, window=10, clock=lambda: now[0])
    t.fail("a")
    t.fail("a")
    assert t.retry_after("a") > 0 and t.retry_after("b") == 0
    now[0] = 11
    assert t.retry_after("a") == 0 and "a" not in t.failures


def test_listening_beyond_this_machine_needs_a_password(tmp_path: Path) -> None:
    auth = Auth(tmp_path)
    check_bind("127.0.0.1", auth)
    with pytest.raises(RuntimeError, match="set-password"):
        check_bind("0.0.0.0", auth)
    auth.set_password(PASSWORD)
    check_bind("0.0.0.0", auth)
