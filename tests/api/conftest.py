"""API fixtures: the database fixtures from tests/db, plus a signed-in test client."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from outbound.api.app import create_app
from outbound.api.deps import Services, build_services
from outbound.bootstrap import Container, container_for
from outbound.config import Settings
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import MembershipRole, PlatformRole
from outbound.providers.adapters.transactional_email import LogEmail
from outbound.services.dns_check import TxtLookup
from outbound.services.settings import SettingsService
from tests.db.conftest import (  # noqa: F401  (fixtures used by name)
    database_url,
    empty_tables,
    engine,
    factory,
    fresh_url,
    other_ws,
    owner_engine,
    platform,
    platform_engine,
    ws,
)
from tests.stages.fakes import FakeLlm

PASSWORD = "plum kettle orbit lantern meadow"  # long enough, not a common one
ADMIN = "admin@customer.example"  # the default signed-in person: an admin of ``ws``
WEBHOOK_SECRET = "whsec-test-secret"
HEADERS = {"X-Requested-With": "outbound"}


def add_user(
    app: FastAPI,
    email: str,
    workspace_id: str | None = None,
    role: MembershipRole = MembershipRole.ADMIN,
    platform_role: PlatformRole | None = None,
) -> str:
    """An account with ``PASSWORD``, a member of ``workspace_id`` (if given). Returns its id."""
    user = app.state.identity.add_user(
        email, PASSWORD, workspace_id=workspace_id, role=role, platform_role=platform_role
    )
    return str(user.id)


def sign_in(app: FastAPI, email: str, workspace_id: str | None = None) -> Api:
    """A fresh client signed in as ``email``, acting in ``workspace_id`` when given."""
    client = TestClient(app)
    response = client.post(
        "/api/auth/login", json={"email": email, "password": PASSWORD}, headers=HEADERS
    )
    assert response.status_code == 200, response.text
    if workspace_id:
        client.headers["X-Workspace-Id"] = workspace_id
    return Api(client)


class Api:
    """A test client that is already signed in and sends the write header."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.app = client.app

    def get(self, path: str, **kwargs: object):  # type: ignore[no-untyped-def]
        return self.client.get(path, **kwargs)  # type: ignore[arg-type]

    def post(self, path: str, **kwargs: object):  # type: ignore[no-untyped-def]
        return self.client.post(path, headers=HEADERS, **kwargs)  # type: ignore[arg-type]

    def put(self, path: str, **kwargs: object):  # type: ignore[no-untyped-def]
        return self.client.put(path, headers=HEADERS, **kwargs)  # type: ignore[arg-type]

    def patch(self, path: str, **kwargs: object):  # type: ignore[no-untyped-def]
        return self.client.patch(path, headers=HEADERS, **kwargs)  # type: ignore[arg-type]

    def delete(self, path: str, **kwargs: object):  # type: ignore[no-untyped-def]
        return self.client.delete(path, headers=HEADERS, **kwargs)  # type: ignore[arg-type]


@pytest.fixture
def container(
    engine: Engine, platform_engine: Engine, factory: UnitOfWorkFactory, tmp_path: Path
) -> Container:
    settings = Settings(
        _env_file=None,
    )
    return container_for(settings, engine, platform_engine)


@pytest.fixture
def outbox() -> LogEmail:
    """Every invitation and reset the app sends, kept instead of sent."""
    return LogEmail()


@pytest.fixture
def make_app(
    container: Container, ws: str, outbox: LogEmail
) -> Callable[..., tuple[FastAPI, Services]]:
    def build(dns_lookup: TxtLookup | None = None) -> tuple[FastAPI, Services]:
        # Never the real resolver: tests make no network calls.
        settings_service = SettingsService(
            container.uow, ws, dns_lookup=dns_lookup or (lambda name: [])
        )
        services = build_services(
            container, ws, settings_service=settings_service, writer=FakeLlm()
        )
        app = create_app(services, web_dist=None, email=outbox)
        add_user(app, ADMIN, ws)
        return app, services

    return build


@pytest.fixture
def app_and_services(make_app: Callable[..., tuple[FastAPI, Services]]) -> tuple[FastAPI, Services]:
    return make_app()


@pytest.fixture
def anonymous(app_and_services: tuple[FastAPI, Services]) -> TestClient:
    return TestClient(app_and_services[0])


@pytest.fixture
def api(anonymous: TestClient) -> Api:
    response = anonymous.post(
        "/api/auth/login", json={"email": ADMIN, "password": PASSWORD}, headers=HEADERS
    )
    assert response.status_code == 200
    return Api(anonymous)


@pytest.fixture
def services(app_and_services: tuple[FastAPI, Services]) -> Services:
    return app_and_services[1]
