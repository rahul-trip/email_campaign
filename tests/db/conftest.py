"""Database fixtures. By default tests run on a temporary SQLite file; set TEST_DATABASE_URL
(for example ``postgresql+psycopg://user:pass@localhost/outbound_test``) to run the same suite
on Postgres, as CI does."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

from outbound.db import migrate
from outbound.db.base import Base
from outbound.db.session import make_engine

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
IS_POSTGRES = bool(TEST_DATABASE_URL and TEST_DATABASE_URL.startswith("postgresql"))


@pytest.fixture(scope="session")
def database_url(tmp_path_factory: pytest.TempPathFactory) -> str:
    if TEST_DATABASE_URL:
        return TEST_DATABASE_URL
    return f"sqlite:///{tmp_path_factory.mktemp('db') / 'test.db'}"


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
    migrate.upgrade(database_url)
    eng = make_engine(database_url)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def empty_tables(request: pytest.FixtureRequest) -> None:
    """Every test that uses the shared engine starts with empty tables."""
    if "engine" not in request.fixturenames:
        return
    eng: Engine = request.getfixturevalue("engine")
    with eng.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())


@pytest.fixture
def fresh_url(tmp_path: Path) -> Iterator[str]:
    """A brand-new, empty database for tests that run migrations themselves."""
    if not IS_POSTGRES:
        yield f"sqlite:///{tmp_path / 'fresh.db'}"
        return
    assert TEST_DATABASE_URL
    base = make_url(TEST_DATABASE_URL)
    name = f"outbound_mig_{uuid.uuid4().hex[:12]}"
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield base.set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


# ----------------------------------------------------------------------- repository fixtures

from outbound.db.session import make_session_factory  # noqa: E402
from outbound.db.uow import UnitOfWorkFactory  # noqa: E402


@pytest.fixture
def factory(engine: Engine) -> UnitOfWorkFactory:
    return UnitOfWorkFactory(make_session_factory(engine))


def make_workspace(factory: UnitOfWorkFactory, name: str = "acme") -> str:
    with factory.admin() as admin:
        workspace = admin.workspaces.create(name, {"legal_name": name}, {"safe_to_send_only": True})
        admin.commit()
    return workspace.id


@pytest.fixture
def ws(factory: UnitOfWorkFactory) -> str:
    return make_workspace(factory)


@pytest.fixture
def other_ws(factory: UnitOfWorkFactory) -> str:
    return make_workspace(factory, "other")
