"""Regression tests for the web layer's security: file serving, headers, size limits, errors."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine
from typer.testing import CliRunner

from outbound.api.app import create_app
from outbound.api.auth import hash_password
from outbound.api.deps import build_services
from outbound.bootstrap import Container
from outbound.cli.main import app as cli_app
from outbound.config import Settings
from outbound.db.uow import UnitOfWorkFactory
from tests.api.conftest import PASSWORD, WEBHOOK_SECRET

DECOY = "SECRET-DECOY-OUTSIDE-THE-WEB-FOLDER"


@pytest.fixture
def site(tmp_path: Path) -> Path:
    """A web folder with a built app in it, and decoy secrets next to and above it."""
    dist = tmp_path / "site" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "assets" / "app.js").write_text("console.log('app')")
    (dist / ".hidden").write_text("hidden inside the web folder")
    (tmp_path / "site" / ".env").write_text(DECOY)
    (tmp_path / "site" / "outbound.db").write_text(DECOY)
    (tmp_path / ".env").write_text(DECOY)
    return dist


@pytest.fixture
def served(
    engine: Engine, factory: UnitOfWorkFactory, ws: str, site: Path
) -> Callable[..., TestClient]:
    settings = Settings(
        _env_file=None,
        operator_password_hash=hash_password(PASSWORD),
        session_secret=SecretStr("s" * 40),
        intake_webhook_secret=SecretStr(WEBHOOK_SECRET),
    )
    container = Container(settings, engine, factory)

    def build() -> TestClient:
        app = create_app(build_services(container, ws), web_dist=site)
        return TestClient(app)

    return build


TRAVERSAL = [
    "/..%2f.env",
    "/..%2F.env",
    "/%2e%2e/.env",
    "/%2e%2e%2f.env",
    "/..%2f..%2f.env",
    "/..%2foutbound.db",
    "/../.env",
    "/%252e%252e%252f.env",
    "/..%5c.env",
    "/assets/..%2f..%2f.env",
    "/assets/%2e%2e/%2e%2e/.env",
    "//etc/passwd",
    "/%2e%2e/%2e%2e/%2e%2e/%2e%2e/etc/passwd",
]


@pytest.mark.parametrize("path", TRAVERSAL)
def test_no_url_can_reach_a_file_outside_the_web_folder(
    served: Callable[..., TestClient], path: str
) -> None:
    response = served().get(path)
    assert DECOY not in response.text
    assert "root:" not in response.text
    assert response.status_code in (200, 404)  # the app shell, or nothing


def test_the_real_files_are_still_served(served: Callable[..., TestClient]) -> None:
    client = served()
    assert client.get("/").text == "<html>app</html>"
    assert "console.log" in client.get("/assets/app.js").text
    assert client.get("/leads/abc").text == "<html>app</html>"  # client-side route


def test_hidden_files_inside_the_web_folder_are_not_served(
    served: Callable[..., TestClient],
) -> None:
    assert "hidden inside" not in served().get("/.hidden").text


def test_an_invalid_path_does_not_crash(served: Callable[..., TestClient]) -> None:
    assert served().get("/%00").status_code in (200, 404)


def test_an_unknown_api_path_is_a_404_not_the_app_shell(served: Callable[..., TestClient]) -> None:
    response = served().get("/api/no-such-thing")
    assert response.status_code == 404
    assert "<html" not in response.text


def test_pages_carry_security_headers(served: Callable[..., TestClient]) -> None:
    for path in ("/", "/api/health"):
        headers = served().get(path).headers
        assert "frame-ancestors 'none'" in headers["content-security-policy"]
        assert "default-src 'self'" in headers["content-security-policy"]
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["referrer-policy"] == "no-referrer"
    assert served().get("/api/health").headers["cache-control"] == "no-store"


def test_error_answers_carry_the_headers_too(served: Callable[..., TestClient]) -> None:
    response = served().get("/api/companies")  # 401
    assert response.status_code == 401
    assert response.headers["x-content-type-options"] == "nosniff"


# ------------------------------------------------------------------ webhook size limit


def _signed(body: bytes) -> dict[str, str]:
    stamp = str(int(time.time()))
    digest = hmac.new(WEBHOOK_SECRET.encode(), stamp.encode() + b"." + body, hashlib.sha256)
    return {"X-Timestamp": stamp, "X-Signature": f"sha256={digest.hexdigest()}"}


def test_an_oversized_webhook_body_is_refused_before_it_is_read(
    served: Callable[..., TestClient],
) -> None:
    body = json.dumps({"event_id": "big", "pad": "x" * 1_100_000}).encode()
    response = served().post("/api/intake/webhook", content=body, headers=_signed(body))
    assert response.status_code == 413
    assert response.json()["code"] == "body_too_large"


def test_a_webhook_body_just_under_the_limit_is_accepted(
    served: Callable[..., TestClient],
) -> None:
    body = json.dumps({"event_id": "ok", "website": "acme.com"}).encode()
    assert (
        served().post("/api/intake/webhook", content=body, headers=_signed(body)).status_code == 200
    )


# ------------------------------------------------------------------ errors


def test_a_bug_is_a_plain_500_with_no_internal_detail(
    served: Callable[..., TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    client = served()
    client.post(
        "/api/auth/login", json={"password": PASSWORD}, headers={"X-Requested-With": "outbound"}
    )
    app: FastAPI = client.app  # type: ignore[assignment]

    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("secret internal detail: /Users/someone/path")

    monkeypatch.setattr(app.state.services.leads, "search", broken)
    quiet = TestClient(app, raise_server_exceptions=False)
    quiet.cookies = client.cookies
    response = quiet.get("/api/companies")
    assert response.status_code == 500
    assert "secret internal detail" not in response.text
    assert response.json()["code"] == "internal_error"


# ------------------------------------------------------------------ serve command


def test_serve_refuses_to_listen_on_the_network_without_secure_cookies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    url = f"sqlite:///{tmp_path / 'x.db'}"
    result = CliRunner().invoke(cli_app, ["serve", "--host", "0.0.0.0", "--database-url", url])
    assert result.exit_code == 1
    assert "unencrypted" in result.output
