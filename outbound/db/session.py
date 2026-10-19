"""Engine and session factory. SQLite gets the settings a real database would have by default."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker


def normalise_url(url: str) -> str:
    """Use psycopg 3 for Postgres URLs that do not name a driver.

    Supabase and most hosts hand out ``postgresql://`` or ``postgres://``, which SQLAlchemy would
    open with psycopg2, which is not installed.
    """
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url.removeprefix(prefix)
    return url


def make_engine(url: str, *, echo: bool = False, pool_size: int = 5) -> Engine:
    url = normalise_url(url)
    if url.startswith("sqlite"):
        engine = create_engine(url, echo=echo, future=True)
        event.listen(engine, "connect", _configure_sqlite)
        return engine
    # A hosted pooler (Supabase's session pooler) allows few clients and closes idle ones, so
    # each process keeps a small fixed pool and checks a connection before using it.
    return create_engine(
        url,
        echo=echo,
        future=True,
        pool_size=pool_size,
        max_overflow=0,
        pool_pre_ping=True,
        pool_recycle=300,
    )


def _configure_sqlite(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")  # SQLite ignores foreign keys unless asked
    cursor.execute(
        "PRAGMA busy_timeout=5000"
    )  # wait instead of failing when another process writes
    cursor.execute("PRAGMA journal_mode=WAL")  # readers do not block the runner's writes
    cursor.close()


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False, future=True)
