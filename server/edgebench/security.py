from __future__ import annotations

from urllib.parse import urlparse

from fastapi import HTTPException, Request


def same_origin(request: Request) -> None:
    """Refuse a state-changing request that a page on another site caused.

    Browsers send an ``Origin`` header on every cross-site POST and DELETE, and there is no CORS, so this stops
    another website from making your browser upload a file or start a conversion here (a ``text/plain`` POST needs
    no preflight). Clients that send no ``Origin`` (curl, scripts, the agents) are not browsers acting for a hostile
    page, and pass.
    """
    origin = request.headers.get("origin")
    if origin is not None and urlparse(origin).netloc != request.headers.get("host"):
        raise HTTPException(403, "Requests from other sites are not accepted.")
