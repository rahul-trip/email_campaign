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


# On Postgres the suite runs as the production roles (Phase 6a): tenant work as outbound_app,
# which row-level security confines to one workspace, and cross-workspace work as
# outbound_platform. The owner (the server's superuser) only migrates and cleans up.
ROLE_PASSWORD = "outbound-test-role"


def role_url(url: str, role: str) -> str:
    return make_url(url).set(username=role, password=ROLE_PASSWORD).render_as_string(False)


@pytest.fixture(scope="session")
def owner_engine(database_url: str) -> Iterator[Engine]:
    migrate.upgrade(database_url)
    eng = make_engine(database_url)
    if IS_POSTGRES:
        with eng.begin() as connection:
            for role in ("outbound_app", "outbound_platform"):
                connection.execute(text(f"ALTER ROLE {role} LOGIN PASSWORD '{ROLE_PASSWORD}'"))
    yield eng
    eng.dispose()


def _role_engine(database_url: str, owner: Engine, role: str) -> Iterator[Engine]:
    if not IS_POSTGRES:
        yield owner
        return
    eng = make_engine(role_url(database_url, role))
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def engine(database_url: str, owner_engine: Engine) -> Iterator[Engine]:
    """Tenant work: outbound_app on Postgres."""
    yield from _role_engine(database_url, owner_engine, "outbound_app")


@pytest.fixture(scope="session")
def platform_engine(database_url: str, owner_engine: Engine) -> Iterator[Engine]:
    """Cross-workspace work: outbound_platform on Postgres."""
    yield from _role_engine(database_url, owner_engine, "outbound_platform")


@pytest.fixture(autouse=True)
def empty_tables(request: pytest.FixtureRequest) -> None:
    """Every test that uses the shared engine starts with empty tables (deleted as the owner:
    the app role would only see one workspace's rows)."""
    if "owner_engine" not in request.fixturenames:  # every database fixture depends on it
        return
    eng: Engine = request.getfixturevalue("owner_engine")
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

from outbound.db.crypto import Keyring  # noqa: E402
from outbound.db.platform import PlatformUnitOfWorkFactory  # noqa: E402
from outbound.db.session import make_session_factory  # noqa: E402
from outbound.db.uow import UnitOfWorkFactory  # noqa: E402
from tests.conftest import TEST_SECRETS_KEYS  # noqa: E402


@pytest.fixture
def factory(engine: Engine) -> UnitOfWorkFactory:
    return UnitOfWorkFactory(
        make_session_factory(engine), keyring=Keyring.from_setting(TEST_SECRETS_KEYS)
    )


@pytest.fixture
def platform(platform_engine: Engine) -> PlatformUnitOfWorkFactory:
    return PlatformUnitOfWorkFactory(make_session_factory(platform_engine))


def make_workspace(platform: PlatformUnitOfWorkFactory, name: str = "acme") -> str:
    with platform() as directory:
        workspace = directory.workspaces.create(
            name, {"legal_name": name}, {"safe_to_send_only": True}
        )
        directory.commit()
    return workspace.id


@pytest.fixture
def ws(platform: PlatformUnitOfWorkFactory) -> str:
    return make_workspace(platform)


@pytest.fixture
def other_ws(platform: PlatformUnitOfWorkFactory) -> str:
    return make_workspace(platform, "other")
