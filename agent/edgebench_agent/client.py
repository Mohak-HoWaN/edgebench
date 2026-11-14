"""The agent's side of the protocol in ADR 0003: outbound HTTP calls only."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

CLAIM_TIMEOUT = httpx.Timeout(60.0, connect=10.0)  # the server holds a claim for up to 25 s
CHUNK = 1024 * 1024


class Rejected(Exception):
    """The server refused this device's token (revoked, or never valid): the agent must be enrolled again."""


class Cancelled(Exception):
    """A download was stopped because the run was cancelled."""


class ServerClient:
    def __init__(self, base_url: str, token: str | None = None, http: httpx.Client | None = None) -> None:
        # ``http`` lets tests hand in the server's own test client; everything else uses a real connection.
        self.http = http or httpx.Client(base_url=base_url.rstrip("/"), timeout=httpx.Timeout(30.0, connect=10.0))
        self.token = token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _check(self, response: httpx.Response) -> httpx.Response:
        if response.status_code == 401:
            raise Rejected(response.json().get("detail", "The server did not accept this device."))
        response.raise_for_status()
        return response

    def enroll(self, enroll_token: str, fingerprint: dict[str, Any], version: str, name: str | None) -> dict[str, Any]:
        body = {"token": enroll_token, "fingerprint": fingerprint, "agent_version": version, "name": name}
        response = self.http.post("/agent/enroll", json=body)
        if response.status_code == 401:
            raise Rejected(response.json().get("detail", "The enrolment token was not accepted."))
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        self.token = data["device_token"]
        return data

    def claim(self) -> dict[str, Any] | None:
        response = self._check(self.http.post("/agent/claim", headers=self._headers(), timeout=CLAIM_TIMEOUT))
        return None if response.status_code == 204 else dict(response.json())

    def heartbeat(
        self,
        job_id: int | None,
        fraction: float | None,
        message: str | None,
        version: str,
        fingerprint: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = {"job_id": job_id, "fraction": fraction, "message": message, "agent_version": version}
        if fingerprint is not None:
            body["fingerprint"] = fingerprint
        return dict(self._check(self.http.post("/agent/heartbeat", json=body, headers=self._headers())).json())

    def result(
        self,
        job_id: int,
        ok: bool,
        kind: str = "failed",
        error: str | None = None,
        result: dict[str, Any] | None = None,
        log: str | None = None,
    ) -> dict[str, Any]:
        body = {"job_id": job_id, "ok": ok, "kind": kind, "error": error, "result": result, "log": log}
        for attempt in range(4):  # the result is the whole point of the run: do not lose it to a blip in the network
            try:
                return dict(self._check(self.http.post("/agent/result", json=body, headers=self._headers())).json())
            except httpx.TransportError:
                if attempt == 3:
                    raise
                time.sleep(2.0)
        raise AssertionError("unreachable")

    def download(self, sha: str, name: str | None, dest: Path, should_stop: Callable[[], bool] = lambda: False) -> None:
        """Fetch ``/agent/artifacts/<sha>[/<name>]`` to ``dest``, resuming a partial file, and stop on a mismatch.

        A bundle file's own hash is not known to the agent (the bundle hash covers all its files), so the caller checks
        bundles as a whole; a plain file is checked here against ``sha``.
        """
        url = f"/agent/artifacts/{sha}" + (f"/{name}" if name else "")
        part = dest.with_name(dest.name + ".part")
        dest.parent.mkdir(parents=True, exist_ok=True)
        offset = part.stat().st_size if part.exists() else 0
        headers = {**self._headers(), **({"Range": f"bytes={offset}-"} if offset else {})}
        with self.http.stream("GET", url, headers=headers) as response:
            if response.status_code == 416:  # we already have all of it
                response.read()
            else:
                self._check(response)
                with part.open("ab" if response.status_code == 206 else "wb") as f:
                    for chunk in response.iter_bytes(CHUNK):
                        if should_stop():
                            raise Cancelled
                        f.write(chunk)
        if name is None and sha256_file(part) != sha:
            part.unlink(missing_ok=True)
            raise ValueError(f"The downloaded file does not match its checksum ({sha[:12]}...). Try again.")
        part.replace(dest)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()
