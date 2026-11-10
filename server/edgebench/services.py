from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Engine

from .artifacts import ArtifactStore
from .config import Settings
from .converter_client import Converter
from .worker import Publish


@dataclass
class Services:
    """What request handlers and job handlers share; built once in the app's lifespan."""

    settings: Settings
    engine: Engine
    store: ArtifactStore
    converter: Converter
    publish: Publish
    # Latest progress an agent reported per job id: {fraction, message}. Memory only; a restart forgets it.
    progress: dict[int, dict[str, Any]] = field(default_factory=dict)
