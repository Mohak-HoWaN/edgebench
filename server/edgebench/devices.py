"""Device tokens and liveness (ADR 0003). Only hashes are stored: a leaked database does not leak a working token."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from fastapi import HTTPException, Request
from sqlmodel import Session, select

from .models import Device, utcnow

ENROLL_TTL = timedelta(hours=1)
ONLINE_WITHIN = timedelta(seconds=30)  # ADR 0003: no heartbeat for 30 s means offline


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token(prefix: str) -> str:
    return f"{prefix}-{secrets.token_urlsafe(32)}"


def is_online(device: Device, now: datetime | None = None) -> bool:
    return device.last_seen_at is not None and (now or utcnow()) - device.last_seen_at <= ONLINE_WITHIN


def kind_from_fingerprint(fingerprint: dict[str, object]) -> str:
    return "pi" if fingerprint.get("pi_model") else "pc"


def authenticate(session: Session, request: Request) -> Device:
    """The device behind ``Authorization: Bearer <device token>``, or 401."""
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "A device token is required.", headers={"WWW-Authenticate": "Bearer"})
    device = session.exec(select(Device).where(Device.token_hash == hash_token(token.strip()))).first()
    if device is None or device.revoked:
        raise HTTPException(401, "That device token is not valid (it may have been revoked).")
    return device
