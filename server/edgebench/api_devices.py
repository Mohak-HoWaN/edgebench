from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from .api_models import services
from .devices import ENROLL_TTL, hash_token, is_online, new_token
from .models import Device, Run, utcnow
from .security import same_origin

router = APIRouter()
guarded = [Depends(same_origin)]


class DeviceOut(BaseModel):
    id: int
    name: str
    expected_kind: str | None
    kind: str | None  # from the agent's own fingerprint, never from the browser
    enrolled: bool
    online: bool
    last_seen_at: datetime | None
    agent_version: str | None
    fingerprint: dict[str, Any] | None
    running_run: int | None
    created_at: datetime


class NewDevice(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    expected_kind: str | None = Field(default=None, pattern="^(pc|pi)$")


class Enrolment(BaseModel):
    device: DeviceOut
    enroll_token: str  # shown once; only its hash is kept
    server_url: str
    expires_minutes: int


def _out(session: Session, d: Device) -> DeviceOut:
    assert d.id is not None
    running = session.exec(
        select(Run.id).where(Run.device_id == d.id, col(Run.outcome).is_(None), col(Run.started_at).is_not(None))
    ).first()
    return DeviceOut(
        id=d.id,
        name=d.name,
        expected_kind=d.expected_kind,
        kind=d.kind,
        enrolled=d.token_hash is not None,
        online=is_online(d),
        last_seen_at=d.last_seen_at,
        agent_version=d.agent_version,
        fingerprint=d.fingerprint,
        running_run=running,
        created_at=d.created_at,
    )


def _device_or_404(session: Session, device_id: int) -> Device:
    d = session.get(Device, device_id)
    if d is None or d.revoked:
        raise HTTPException(404, "There is no such device.")
    return d


def _server_url(request: Request) -> str:
    return f"{request.url.scheme}://{request.headers.get('host', 'localhost:8000')}"


def _issue_enroll_token(session: Session, d: Device) -> str:
    token = new_token("eb-enroll")
    d.enroll_hash, d.enroll_expires_at = hash_token(token), utcnow() + ENROLL_TTL
    session.add(d)
    session.commit()
    return token


@router.get("/api/devices")
def list_devices(request: Request) -> list[DeviceOut]:
    with Session(services(request).engine) as session:
        rows = session.exec(select(Device).where(col(Device.revoked).is_(False)).order_by(col(Device.id)))
        return [_out(session, d) for d in rows]


@router.post("/api/devices", status_code=201, dependencies=guarded)
def add_device(body: NewDevice, request: Request) -> Enrolment:
    """Register a device and get the one-time token its agent uses to connect. The token is valid for an hour."""
    s = services(request)
    with Session(s.engine) as session:
        d = Device(name=body.name.strip(), expected_kind=body.expected_kind)
        session.add(d)
        session.commit()
        session.refresh(d)
        token = _issue_enroll_token(session, d)
        out = _out(session, d)
    s.publish({"type": "device.updated", "id": out.id})
    return Enrolment(device=out, enroll_token=token, server_url=_server_url(request), expires_minutes=60)


@router.post("/api/devices/{device_id}/enroll-token", dependencies=guarded)
def reissue_token(device_id: int, request: Request) -> Enrolment:
    """A new one-time token for a device that has to connect again. The old device token stops working."""
    s = services(request)
    with Session(s.engine) as session:
        d = _device_or_404(session, device_id)
        d.token_hash = None
        token = _issue_enroll_token(session, d)
        out = _out(session, d)
    s.publish({"type": "device.updated", "id": device_id})
    return Enrolment(device=out, enroll_token=token, server_url=_server_url(request), expires_minutes=60)


@router.delete("/api/devices/{device_id}", status_code=204, dependencies=guarded)
def remove_device(device_id: int, request: Request) -> Response:
    """Revoke a device: its token stops working at once and it leaves the list."""
    s = services(request)
    with Session(s.engine) as session:
        d = _device_or_404(session, device_id)
        d.revoked, d.token_hash, d.enroll_hash = True, None, None
        session.add(d)
        session.commit()
    s.publish({"type": "device.updated", "id": device_id})
    return Response(status_code=204)
