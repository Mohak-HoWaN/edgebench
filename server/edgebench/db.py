from __future__ import annotations

from pathlib import Path
from sqlite3 import Connection as SQLiteConnection
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event

MIGRATIONS = Path(__file__).parent / "migrations"


def _pragmas(dbapi_connection: Any, _record: Any) -> None:
    if isinstance(dbapi_connection, SQLiteConnection):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()


def make_engine(db_path: Path) -> Engine:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", connect_args={"check_same_thread": False})
    event.listen(engine, "connect", _pragmas)
    return engine


def _alembic_config(db_path: Path) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    return cfg


def migrate(db_path: Path, revision: str = "head") -> None:
    """Bring the database to ``revision``. Called at start-up so the app never runs against an old schema."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(_alembic_config(db_path), revision)


def downgrade(db_path: Path, revision: str) -> None:
    command.downgrade(_alembic_config(db_path), revision)
