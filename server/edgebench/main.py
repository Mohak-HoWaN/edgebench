from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse

from . import __version__
from .api import router
from .api_agent import router as agent_router
from .api_auth import router as auth_router
from .api_datasets import router as datasets_router
from .api_devices import router as devices_router
from .api_experiments import router as experiments_router
from .api_models import router as models_router
from .api_runs import router as runs_router
from .artifacts import ArtifactStore
from .auth import Auth, AuthGate, check_bind
from .config import Settings, get_settings
from .converter_client import Converter
from .dataset_versions import register_dataset_handlers
from .db import make_engine, migrate
from .events import EventHub
from .logs import configure_logging
from .model_jobs import register_handlers
from .services import Services
from .worker import Worker

log = logging.getLogger(__name__)


def _mount_spa(app: FastAPI, dist: Path) -> None:
    """Serve the built frontend. Unknown paths return index.html so client-side routes survive a reload."""
    root = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path in ("api", "ws") or path.startswith(("api/", "ws/")):
            raise HTTPException(404)
        target = (root / path).resolve()
        if target.is_file() and root in target.parents:  # the parents check refuses ../ escapes
            return FileResponse(target)
        if Path(path).suffix or path.startswith("assets/"):
            # A missing file (an old tab asking for a chunk the new build renamed) must be a 404, not the HTML shell.
            raise HTTPException(404)
        return FileResponse(root / "index.html")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    auth = Auth(settings.data_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        check_bind(settings.host, auth)
        configure_logging(settings.log_level)
        migrate(settings.db_path)
        engine = make_engine(settings.db_path)
        hub = EventHub()
        hub.bind(asyncio.get_running_loop())
        worker = (
            Worker(
                engine,
                hub.publish,
                poll_seconds=settings.worker_poll_seconds,
                heartbeat_seconds=settings.heartbeat_seconds,
                stale_seconds=settings.stale_seconds,
            )
            if settings.worker_enabled
            else None
        )
        store = ArtifactStore(settings.data_dir / "artifacts")
        store.clean_tmp()  # half-written files from a run that was killed; no job is running yet
        services = Services(settings, engine, store, Converter(settings), hub.publish)
        register_handlers(services)
        register_dataset_handlers(services)
        app.state.settings, app.state.engine, app.state.hub, app.state.worker = settings, engine, hub, worker
        app.state.services = services
        app.state.started = time.monotonic()
        if worker is not None:
            worker.start()
        log.info("server started", extra={"version": __version__, "data_dir": str(settings.data_dir)})
        try:
            yield
        finally:
            if worker is not None:
                worker.stop()
            engine.dispose()

    app = FastAPI(title="EdgeBench", version=__version__, lifespan=lifespan)
    app.state.auth = auth
    app.add_middleware(AuthGate, auth=auth)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)  # added last = runs first
    app.include_router(auth_router)
    app.include_router(router)
    app.include_router(models_router)
    app.include_router(datasets_router)
    app.include_router(devices_router)
    app.include_router(runs_router)
    app.include_router(experiments_router)
    app.include_router(agent_router)
    if settings.web_dist is not None and settings.web_dist.is_dir():
        _mount_spa(app, settings.web_dist)
    return app


app = create_app()
