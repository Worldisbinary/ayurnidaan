"""Database engine and session handling (SQLite locally, Postgres in production).

Connection pooling: opening a Postgres connection costs a TCP + TLS handshake and a
backend process fork (tens of ms, more across regions to Neon). SQLAlchemy's QueuePool
keeps up to ``pool_size`` connections open per worker process and lends them out per
request, with ``max_overflow`` extra under bursts. ``pool_pre_ping`` tests a connection
before use (Neon may have closed it while idle), and ``pool_recycle`` retires old ones
before the server does. Neon's ``-pooler`` endpoint is PgBouncer in transaction mode,
which cannot keep server-side prepared statements across transactions, so psycopg's
automatic statement preparation is turned off there.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def normalise_url(url: str) -> str:
    if url.startswith("postgres://"):  # Neon/Heroku style URLs
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


def make_engine(
    url: str,
    pool_size: int = 5,
    max_overflow: int = 5,
    pool_timeout: float = 10.0,
    pool_recycle: int = 300,
) -> Engine:
    url = normalise_url(url)
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs.update(
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            pool_recycle=pool_recycle,
        )
        if "-pooler." in url:
            kwargs["connect_args"] = {"prepare_threshold": None}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):  # SQLite ignores foreign keys unless asked
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return engine


class Database:
    def __init__(self, url: str, **pool):
        self.engine = make_engine(url, **pool)
        self.SessionLocal = sessionmaker(self.engine, expire_on_commit=False)

    def session(self) -> Iterator[Session]:
        with self.SessionLocal() as s:
            yield s

    def checked_out(self) -> int:
        """Connections currently lent out (0 for SQLite's per-thread pool)."""
        return getattr(self.engine.pool, "checkedout", lambda: 0)()
