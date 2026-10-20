"""API fixtures: the database fixtures from tests/db, plus a signed-in test client."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine

from outbound.api.app import create_app
from outbound.api.auth import hash_password
from outbound.api.deps import Services, build_services
from outbound.bootstrap import Container
from outbound.config import Settings
from outbound.db.uow import UnitOfWorkFactory
from outbound.services.dns_check import TxtLookup
from outbound.services.settings import SettingsService
from tests.db.conftest import (  # noqa: F401  (fixtures used by name)
    database_url,
    empty_tables,
    engine,
    factory,
    fresh_url,
    other_ws,
    ws,
)

PASSWORD = "correct horse battery staple"
WEBHOOK_SECRET = "whsec-test-secret"
HEADERS = {"X-Requested-With": "outbound"}


class Api:
    """A test client that is already signed in and sends the write header."""

    def __init__(self, client: TestClient) -> None:
        self.client = client

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
def container(engine: Engine, factory: UnitOfWorkFactory, tmp_path: Path) -> Container:
    settings = Settings(
        _env_file=None,
        operator_password_hash=hash_password(PASSWORD),
        session_secret=SecretStr("s" * 40),
        intake_webhook_secret=SecretStr(WEBHOOK_SECRET),
    )
    return Container(settings, engine, factory)


@pytest.fixture
def make_app(container: Container, ws: str) -> Callable[..., tuple[FastAPI, Services]]:
    def build(dns_lookup: TxtLookup | None = None) -> tuple[FastAPI, Services]:
        # Never the real resolver: tests make no network calls.
        settings_service = SettingsService(
            container.uow, ws, dns_lookup=dns_lookup or (lambda name: [])
        )
        services = build_services(container, ws, settings_service=settings_service)
        return create_app(services, web_dist=None), services

    return build


@pytest.fixture
def app_and_services(make_app: Callable[..., tuple[FastAPI, Services]]) -> tuple[FastAPI, Services]:
    return make_app()


@pytest.fixture
def anonymous(app_and_services: tuple[FastAPI, Services]) -> TestClient:
    return TestClient(app_and_services[0])


@pytest.fixture
def api(anonymous: TestClient) -> Api:
    response = anonymous.post("/api/auth/login", json={"password": PASSWORD}, headers=HEADERS)
    assert response.status_code == 200
    return Api(anonymous)


@pytest.fixture
def services(app_and_services: tuple[FastAPI, Services]) -> Services:
    return app_and_services[1]
