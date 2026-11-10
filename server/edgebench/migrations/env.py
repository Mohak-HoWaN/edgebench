from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool
from sqlmodel import SQLModel

from edgebench import models  # noqa: F401  (registers the tables on SQLModel.metadata)

config = context.config
target_metadata = SQLModel.metadata


def run_migrations() -> None:
    engine = create_engine(config.get_main_option("sqlalchemy.url") or "", poolclass=pool.NullPool)
    with engine.connect() as connection:
        # Batch mode: SQLite cannot ALTER most things in place, so later migrations rebuild the table.
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


run_migrations()
