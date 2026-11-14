from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .auth import COOKIE, SESSION_SECONDS, Auth
from .security import same_origin

router = APIRouter(prefix="/api/auth")


class Login(BaseModel):
    password: str = Field(max_length=200)


class Status(BaseModel):
    enabled: bool  # false until the owner sets a password; then the site is open on this machine only
    signed_in: bool


def auth_of(request: Request) -> Auth:
    auth: Auth = request.app.state.auth
    return auth


def client_ip(request: Request) -> str:
    # Behind a reverse proxy or tunnel this is the proxy's address, so the throttle then counts everyone together.
    return request.client.host if request.client else "-"


@router.get("/status")
def status(request: Request) -> Status:
    auth = auth_of(request)
    return Status(enabled=auth.enabled, signed_in=auth.valid(request.cookies.get(COOKIE)))


@router.post("/login", dependencies=[Depends(same_origin)])
def login(body: Login, request: Request, response: Response) -> Status:
    auth, ip = auth_of(request), client_ip(request)
    if not auth.enabled:
        raise HTTPException(409, "No owner password is set. Run `python -m edgebench set-password` on the server.")
    wait = auth.login_throttle.retry_after(ip)
    if wait:
        raise HTTPException(
            429, f"Too many wrong passwords. Try again in {wait} s.", headers={"Retry-After": str(wait)}
        )
    if not auth.check_password(body.password):
        auth.login_throttle.fail(ip)
        raise HTTPException(401, "That password is not right.")
    secure = request.url.scheme == "https" or request.app.state.settings.secure_cookie
    response.set_cookie(
        COOKIE, auth.open_session(), max_age=SESSION_SECONDS, httponly=True, samesite="strict", secure=secure, path="/"
    )
    return Status(enabled=True, signed_in=True)


@router.post("/logout", dependencies=[Depends(same_origin)])
def logout(request: Request, response: Response) -> Status:
    auth_of(request).close_session(request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path="/")
    return Status(enabled=auth_of(request).enabled, signed_in=False)
