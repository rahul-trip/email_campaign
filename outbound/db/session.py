"""Engine and session factory. SQLite gets the settings a real database would have by default."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, Engine, create_engine, event, text
from sqlalchemy.orm import Session, SessionTransaction, sessionmaker

# The row-level-security key (Phase 6a). Set inside every transaction, never for the session:
# a pooled connection must not carry one workspace's key into its next use.
WORKSPACE_SETTING = "app.workspace_id"


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
    factory = sessionmaker(engine, expire_on_commit=False, future=True)
    event.listen(factory, "after_begin", _set_workspace)
    return factory


def _set_workspace(
    session: Session, _transaction: SessionTransaction, connection: Connection
) -> None:
    """Tell Postgres which workspace this transaction belongs to, for row-level security.

    A tenant unit of work puts its workspace in ``session.info``; the listener runs at the
    start of every transaction, including the new one SQLAlchemy begins after a commit in the
    middle of a unit of work. ``set_config(..., true)`` lasts until the transaction ends.
    Without a workspace (the platform unit of work) nothing is set, and a tenant table then
    shows the app role no rows at all.
    """
    if connection.dialect.name != "postgresql":
        return
    workspace_id = session.info.get("workspace_id")
    if workspace_id is not None:
        connection.execute(
            text("SELECT set_config(:name, :value, true)"),
            {"name": WORKSPACE_SETTING, "value": workspace_id},
        )
    if session.info.get("read_only"):
        connection.execute(text("SET TRANSACTION READ ONLY"))
