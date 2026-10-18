"""Login, the write header, throttling, and the shape of errors."""

from __future__ import annotations

from fastapi.testclient import TestClient

from outbound.api.auth import LoginThrottle, Sessions, hash_password, verify_password
from tests.api.conftest import HEADERS, PASSWORD, Api


def test_the_api_needs_a_login(anonymous: TestClient) -> None:
    for path in ("/api/companies", "/api/review", "/api/runs", "/api/settings/campaigns"):
        response = anonymous.get(path)
        assert response.status_code == 401
        assert response.json()["code"] == "unauthenticated"


def test_health_and_docs_are_open(anonymous: TestClient) -> None:
    assert anonymous.get("/api/health").json() == {"status": "ok"}
    assert anonymous.get("/openapi.json").status_code == 200


def test_a_wrong_password_is_refused(anonymous: TestClient) -> None:
    response = anonymous.post("/api/auth/login", json={"password": "nope"}, headers=HEADERS)
    assert response.status_code == 401 and response.json()["code"] == "bad_credentials"
    assert anonymous.get("/api/companies").status_code == 401


def test_logging_in_sets_a_strict_http_only_cookie_and_logging_out_clears_it(
    anonymous: TestClient,
) -> None:
    response = anonymous.post("/api/auth/login", json={"password": PASSWORD}, headers=HEADERS)
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert anonymous.get("/api/auth/me").json() == {"user": "operator"}
    anonymous.post("/api/auth/logout", headers=HEADERS)
    assert anonymous.get("/api/auth/me").status_code == 401


def test_a_forged_or_tampered_cookie_is_not_accepted(anonymous: TestClient) -> None:
    anonymous.cookies.set("outbound_session", "not-a-real-token")
    assert anonymous.get("/api/companies").status_code == 401


def test_repeated_bad_passwords_are_throttled(anonymous: TestClient) -> None:
    codes = [
        anonymous.post("/api/auth/login", json={"password": "x"}, headers=HEADERS).status_code
        for _ in range(7)
    ]
    assert codes[:5] == [401] * 5 and codes[5:] == [429, 429]
    good = anonymous.post("/api/auth/login", json={"password": PASSWORD}, headers=HEADERS)
    assert good.status_code == 429  # even the right password waits out the window


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


def test_password_hashes_verify_and_reject() -> None:
    hashed = hash_password("hunter2 hunter2")
    assert verify_password(hashed, "hunter2 hunter2")
    assert not verify_password(hashed, "hunter3")
    assert not verify_password("not a hash", "anything")


def test_sessions_expire_and_need_a_long_secret() -> None:
    sessions = Sessions("x" * 32, hours=-1)
    assert not sessions.valid(sessions.issue())  # a session whose time has already run out
    assert not Sessions("x" * 32, 1).valid(None)
    try:
        Sessions("short", 1)
    except ValueError:
        pass
    else:
        raise AssertionError("a short secret must be refused")


def test_the_throttle_forgets_old_failures() -> None:
    throttle = LoginThrottle(attempts=2, window=10)
    throttle.failed("c", now=0)
    throttle.failed("c", now=1)
    assert throttle.blocked("c", now=2)
    assert not throttle.blocked("c", now=20)
    throttle.failed("c", now=21)
    throttle.succeeded("c")
    assert not throttle.blocked("c", now=22)
