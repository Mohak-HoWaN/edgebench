from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Server settings. Every field can be overridden with an ``EDGEBENCH_`` environment variable or a ``.env`` file."""

    model_config = SettingsConfigDict(env_prefix="EDGEBENCH_", env_file=".env", extra="ignore")

    data_dir: Path = Path("data")
    # Local only by default; exposing the server on the LAN is a Phase 5 decision that needs device tokens (ADR 0003).
    host: str = "127.0.0.1"
    port: int = 8000
    # Host names the server answers to. Refusing the rest blocks DNS-rebinding pages (hostile name -> 127.0.0.1).
    # No IPv6 literal: Starlette splits the Host header at the first ":", so "[::1]:8000" can never match.
    allowed_hosts: list[str] = ["localhost", "127.0.0.1"]
    log_level: str = "INFO"
    # Conversions run in a separate Python with torch, ultralytics, onnx, OpenVINO and ncnn (converter/README.md).
    # Without it the server still runs, but models cannot be read or converted and the Models page says so.
    converter_python: Path | None = None
    converter_dir: Path = Path(__file__).resolve().parents[2] / "converter"
    converter_timeout_seconds: float = 900.0
    max_upload_bytes: int = 1024**3
    max_dataset_upload_bytes: int = 4 * 1024**3
    max_dataset_unpacked_bytes: int = 16 * 1024**3
    max_dataset_files: int = 200_000
    # NDJSON datasets name picture addresses; only public ones are fetched unless this allows your own image server
    allow_private_ndjson_urls: bool = False
    web_dist: Path | None = None
    worker_enabled: bool = True
    worker_poll_seconds: float = 0.5
    heartbeat_seconds: float = 5.0
    stale_seconds: float = 30.0

    @property
    def db_path(self) -> Path:
        return self.data_dir / "edgebench.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()
