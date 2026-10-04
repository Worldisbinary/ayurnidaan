"""Alembic environment: URL from AYUR_DATABASE_URL, metadata from the ORM models."""

from __future__ import annotations

from alembic import context

from ayurnidaan.app import models  # noqa: F401  (registers tables on Base.metadata)
from ayurnidaan.app.db import Base, make_engine
from ayurnidaan.config import Settings

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or Settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(_url())
    with engine.connect() as connection:
        # batch mode lets ALTER TABLE work on SQLite too
        context.configure(
            connection=connection, target_metadata=target_metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
