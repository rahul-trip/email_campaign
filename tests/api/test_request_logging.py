"""One line per request with an id, no query string, and an id the operator can quote."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from outbound.api.deps import Services
from outbound.logging import clear, configure_logging
from tests.api.conftest import ADMIN, HEADERS, PASSWORD, Api


def lines(capsys: pytest.CaptureFixture[str], event: str) -> list[dict[str, object]]:
    parsed = [
        json.loads(line) for line in capsys.readouterr().err.splitlines() if line.startswith("{")
    ]
    return [line for line in parsed if line["event"] == event]


@pytest.fixture(autouse=True)
def json_logs() -> None:
    configure_logging("INFO", "json", "test")
    clear()


def test_a_request_is_logged_once_with_the_route_not_the_query(
    api: Api, capsys: pytest.CaptureFixture[str]
) -> None:
    response = api.get("/api/companies/abc/waterfall?token=SECRET&q=jane@acme.com")
    [line] = lines(capsys, "http_request")
    assert line["method"] == "GET" and line["status"] == response.status_code == 404
    assert line["path"] == "/api/companies/{company_id}/waterfall"
    assert isinstance(line["duration_ms"], int) and line["level"] == "warning"
    assert "SECRET" not in json.dumps(line) and "acme" not in json.dumps(line)


def test_the_response_carries_the_request_id_and_it_matches_the_log(
    api: Api, capsys: pytest.CaptureFixture[str]
) -> None:
    response = api.get("/api/companies")
    [line] = lines(capsys, "http_request")
    assert response.headers["X-Request-ID"] == line["request_id"]
    assert line["level"] == "info" and line["client_ip"]


def test_a_well_formed_caller_id_is_kept_and_a_malformed_one_is_replaced(
    api: Api, capsys: pytest.CaptureFixture[str]
) -> None:
    kept = api.get("/api/companies", headers={"X-Request-ID": "trace-12345678"})
    assert kept.headers["X-Request-ID"] == "trace-12345678"
    replaced = api.get("/api/companies", headers={"X-Request-ID": "x\ny; DROP"})
    assert replaced.headers["X-Request-ID"] not in {"x\ny; DROP", ""}
    ids = [line["request_id"] for line in lines(capsys, "http_request")]
    assert ids[0] == "trace-12345678" and ids[1] == replaced.headers["X-Request-ID"]


def test_health_checks_are_not_logged_at_info(api: Api, capsys: pytest.CaptureFixture[str]) -> None:
    api.get("/api/health")
    assert lines(capsys, "http_request") == []


def test_login_attempts_are_audited_without_the_password(
    anonymous: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    anonymous.post(
        "/api/auth/login", json={"email": ADMIN, "password": "wrong-guess-1"}, headers=HEADERS
    )
    anonymous.post("/api/auth/login", json={"email": ADMIN, "password": PASSWORD}, headers=HEADERS)
    out = capsys.readouterr().err
    events = [json.loads(x) for x in out.splitlines() if x.startswith("{")]
    names = [e["event"] for e in events if e["event"].startswith("login_")]
    assert names == ["login_failed", "login_succeeded"]
    assert all(e["client_ip"] for e in events if e["event"].startswith("login_"))
    assert "wrong-guess-1" not in out and PASSWORD not in out


def test_a_bug_gives_the_operator_a_reference_that_finds_its_log_line(
    app_and_services: tuple[FastAPI, Services],
    api: Api,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    app, services = app_and_services

    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom for jane@acme.com")

    monkeypatch.setattr(services.leads, "search", broken)
    quiet = TestClient(app, raise_server_exceptions=False)
    quiet.cookies = api.client.cookies
    response = quiet.get("/api/companies")
    reference = response.headers["X-Request-ID"]
    assert response.status_code == 500 and reference in response.json()["detail"]
    events = [json.loads(x) for x in capsys.readouterr().err.splitlines() if x.startswith("{")]
    [bug] = [e for e in events if e["event"] == "unhandled_error"]
    assert bug["request_id"] == reference and bug["path"] == "/api/companies"
    assert bug["error_type"] == "RuntimeError" and "jane@acme.com" not in json.dumps(bug)
    [request_line] = [e for e in events if e["event"] == "http_request"]
    assert request_line["status"] == 500 and request_line["request_id"] == reference
