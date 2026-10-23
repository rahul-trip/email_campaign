"""Signing in, the write header, throttling, and the shape of errors."""

from __future__ import annotations

from fastapi.testclient import TestClient

from outbound.api.auth import LoginThrottle
from tests.api.conftest import ADMIN, HEADERS, PASSWORD, Api


def login(client: TestClient, email: str = ADMIN, password: str = PASSWORD):  # type: ignore[no-untyped-def]
    return client.post(
        "/api/auth/login", json={"email": email, "password": password}, headers=HEADERS
    )


def test_the_api_needs_a_sign_in(anonymous: TestClient) -> None:
    for path in ("/api/companies", "/api/review", "/api/runs", "/api/settings/campaigns"):
        response = anonymous.get(path)
        assert response.status_code == 401
        assert response.json()["code"] == "unauthenticated"


def test_only_health_is_open_and_the_api_document_needs_a_sign_in(
    anonymous: TestClient, api: Api
) -> None:
    fresh = TestClient(anonymous.app)  # no session cookie
    assert fresh.get("/api/health").json() == {"status": "ok"}
    assert fresh.get("/api/openapi.json").status_code == 401
    assert fresh.get("/openapi.json").status_code == 404
    assert fresh.get("/api/docs").status_code == 404
    assert api.get("/api/openapi.json").json()["info"]["title"] == "Outbound"


def test_a_wrong_password_or_unknown_address_gets_the_same_answer(anonymous: TestClient) -> None:
    wrong = login(anonymous, password="not the right password at all")
    unknown = login(anonymous, email="nobody@nowhere.example")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["code"] == unknown.json()["code"] == "bad_credentials"
    assert wrong.json()["detail"] == unknown.json()["detail"]
    assert anonymous.get("/api/companies").status_code == 401


def test_signing_in_sets_a_strict_http_only_cookie_and_signing_out_ends_the_session(
    anonymous: TestClient, ws: str
) -> None:
    response = login(anonymous, email=ADMIN.upper())  # addresses are not case-sensitive
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    me = anonymous.get("/api/auth/me").json()
    assert me["user"]["email"] == ADMIN
    assert [(w["id"], w["role"]) for w in me["workspaces"]] == [(ws, "admin")]
    token = anonymous.cookies.get("outbound_session")
    anonymous.post("/api/auth/logout", headers=HEADERS)
    assert anonymous.get("/api/auth/me").status_code == 401
    # the old token is dead on the server, not just forgotten by this browser
    replay = TestClient(anonymous.app)
    replay.cookies.set("outbound_session", token or "")
    assert replay.get("/api/companies").status_code == 401


def test_a_forged_cookie_is_not_accepted(anonymous: TestClient) -> None:
    anonymous.cookies.set("outbound_session", "not-a-real-token")
    assert anonymous.get("/api/companies").status_code == 401


def test_repeated_bad_passwords_are_throttled(anonymous: TestClient) -> None:
    codes = [login(anonymous, password=f"wrong guess {i}").status_code for i in range(7)]
    assert codes[:5] == [401] * 5 and codes[5:] == [429, 429]
    assert login(anonymous).status_code == 429  # even the right password waits out the window


def test_a_write_without_the_header_is_refused_even_when_signed_in(
    api: Api, anonymous: TestClient
) -> None:
    response = anonymous.post("/api/targets", json={"website": "acme.com"})
    assert response.status_code == 403 and response.json()["code"] == "missing_header"


def test_errors_are_problem_details_with_a_stable_code(api: Api) -> None:
    response = api.get("/api/companies/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert (body["code"], body["status"]) == ("not_found", 404)
    assert body["type"] == "urn:outbound:not_found"


def test_invalid_input_lists_the_bad_fields(api: Api) -> None:
    response = api.post("/api/targets", json={"priority": 99, "unknown": 1})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_failed"
    assert {e["field"] for e in body["errors"]} >= {"priority", "unknown"}


def test_the_throttle_forgets_old_failures() -> None:
    throttle = LoginThrottle(attempts=2, window=10)
    throttle.failed("c", now=0)
    throttle.failed("c", now=1)
    assert throttle.blocked("c", now=2)
    assert not throttle.blocked("c", now=20)
    throttle.failed("c", now=21)
    throttle.succeeded("c")
    assert not throttle.blocked("c", now=22)
