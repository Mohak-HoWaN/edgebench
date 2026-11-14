"""Owner login (ADR 0005): one password, set from the command line, a session cookie, and a throttle on guesses.

Until a password is set nothing here is active and the server stays on this machine. Once it is set, every ``/api`` and
``/ws`` route needs the session cookie; ``/agent`` keeps its own device tokens (ADR 0003) and the built web pages are
public (they hold no data).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable
from pathlib import Path

from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

COOKIE = "eb_session"
SESSION_SECONDS = 7 * 24 * 3600
MIN_PASSWORD = 12
LOOPBACK = ("127.0.0.1", "localhost", "::1")
_N, _R, _P = 2**15, 8, 1  # scrypt cost: about 100 ms and 32 MB per guess


def _scrypt(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, maxmem=64 * 1024 * 1024)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    return f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(_scrypt(password, salt)).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        kind, salt, digest = stored.split("$")
        return kind == "scrypt" and hmac.compare_digest(
            _scrypt(password, base64.b64decode(salt)), base64.b64decode(digest)
        )
    except ValueError:
        return False


class Throttle:
    """At most ``limit`` failures per key in ``window`` seconds; a key over it waits for its oldest to age out."""

    def __init__(self, limit: int = 5, window: float = 300.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit, self.window, self.clock = limit, window, clock
        self.failures: dict[str, list[float]] = {}

    def _recent(self, key: str) -> list[float]:
        cutoff = self.clock() - self.window
        recent = [t for t in self.failures.get(key, []) if t > cutoff]
        if recent:
            self.failures[key] = recent
        else:
            self.failures.pop(key, None)  # keeps the table from growing with every address that ever failed once
        return recent

    def retry_after(self, key: str) -> int:
        """Seconds to wait before this key may try again; 0 when it may."""
        recent = self._recent(key)
        return 0 if len(recent) < self.limit else int(recent[0] + self.window - self.clock()) + 1

    def fail(self, key: str) -> None:
        self.failures.setdefault(key, []).append(self.clock())


class Auth:
    # shortcut: sessions live in memory, so a server restart signs the owner out; upgrade if that gets annoying.
    def __init__(self, data_dir: Path) -> None:
        self.file = data_dir / "owner.json"
        self.sessions: dict[str, float] = {}  # sha256 of the cookie value -> expiry (wall clock)
        self.login_throttle = Throttle()
        self.enroll_throttle = Throttle(limit=10)

    @property
    def enabled(self) -> bool:
        return self.file.exists()

    def set_password(self, password: str) -> None:
        if len(password) < MIN_PASSWORD:
            raise ValueError(f"Use at least {MIN_PASSWORD} characters.")
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps({"password": hash_password(password)}), encoding="utf-8")
        self.file.chmod(0o600)  # no effect on Windows, where the data folder's own permissions apply
        self.sessions.clear()  # a changed password signs everyone out

    def check_password(self, password: str) -> bool:
        try:
            stored = json.loads(self.file.read_text(encoding="utf-8"))["password"]
        except (OSError, ValueError, KeyError):
            return False
        return verify_password(password, str(stored))

    @staticmethod
    def _key(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def open_session(self) -> str:
        token = secrets.token_urlsafe(32)
        self.sessions[self._key(token)] = time.time() + SESSION_SECONDS
        return token

    def valid(self, token: str | None) -> bool:
        if not token:
            return False
        now = time.time()
        for key in [k for k, until in self.sessions.items() if until <= now]:
            del self.sessions[key]
        return self._key(token) in self.sessions

    def close_session(self, token: str | None) -> None:
        if token:
            self.sessions.pop(self._key(token), None)


def check_bind(host: str, auth: Auth) -> None:
    """Refuse to listen beyond this machine while anyone could reach the whole site without a password."""
    if host not in LOOPBACK and not auth.enabled:
        raise RuntimeError(
            f"Refusing to listen on {host}: no owner password is set, so anyone on the network could use the site. "
            "Run `python -m edgebench set-password` first. Also list the names you will use in EDGEBENCH_ALLOWED_HOSTS."
        )


def _gated(path: str) -> bool:
    return (path.startswith("/api/") or path.startswith("/ws/")) and not path.startswith("/api/auth/")


class AuthGate:
    """Pure ASGI (not BaseHTTPMiddleware) so it also covers WebSockets."""

    def __init__(self, app: ASGIApp, auth: Auth) -> None:
        self.app, self.auth = app, auth

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        gated = scope["type"] in ("http", "websocket") and self.auth.enabled and _gated(scope["path"])
        if gated and not self.auth.valid(HTTPConnection(scope).cookies.get(COOKIE)):
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                await JSONResponse({"detail": "Sign in first."}, status_code=401)(scope, receive, send)
            return
        await self.app(scope, receive, send)
