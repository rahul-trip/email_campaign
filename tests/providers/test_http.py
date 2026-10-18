"""HttpClient: retry policy and error mapping, with a mock transport and no sleeping."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from tenacity import wait_none

from outbound.providers.errors import ProviderAuthError, ProviderError, RateLimited
from outbound.providers.http import HttpClient


def make_client(
    handler: Callable[[httpx.Request], httpx.Response], attempts: int = 3
) -> HttpClient:
    return HttpClient(
        "acme",
        "https://api.acme.test/v1",
        attempts=attempts,
        wait=wait_none(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_returns_parsed_json() -> None:
    client = make_client(lambda request: httpx.Response(200, json={"ok": True}))
    assert client.get_json("/ping") == {"ok": True}


def test_retries_5xx_then_succeeds() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json={"n": 3})

    assert make_client(handler).get_json("/x") == {"n": 3}
    assert len(calls) == 3


def test_gives_up_after_attempts_on_5xx() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(500)

    with pytest.raises(ProviderError) as info:
        make_client(handler, attempts=3).get_json("/x")
    assert len(calls) == 3
    assert info.value.status_code == 500
    assert info.value.retryable


def test_429_raises_rate_limited_after_retries_and_reads_retry_after() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(429, headers={"retry-after": "7"})

    with pytest.raises(RateLimited) as info:
        make_client(handler, attempts=2).get_json("/x")
    assert len(calls) == 2
    assert info.value.retry_after == 7.0


@pytest.mark.parametrize("status", [401, 403])
def test_auth_errors_fail_at_once(status: int) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(status)

    with pytest.raises(ProviderAuthError):
        make_client(handler).get_json("/x")
    assert len(calls) == 1


def test_other_4xx_is_not_retried() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(422)

    with pytest.raises(ProviderError) as info:
        make_client(handler).post_json("/x", {"a": 1})
    assert len(calls) == 1
    assert not info.value.retryable


def test_transport_errors_are_retried() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ConnectTimeout("boom", request=request)

    with pytest.raises(ProviderError):
        make_client(handler, attempts=3).get_json("/x")
    assert len(calls) == 3


def test_202_is_polled_again_until_done() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(202) if len(calls) < 2 else httpx.Response(200, json={"done": True})

    assert make_client(handler).get_json("/verify") == {"done": True}
    assert len(calls) == 2


def test_require_api_key_rejects_blank_and_strips() -> None:
    from outbound.providers.http import require_api_key

    with pytest.raises(ProviderAuthError):
        require_api_key("acme", "  ")
    assert require_api_key("acme", " k ") == "k"


def test_non_json_body_is_a_provider_error() -> None:
    client = make_client(lambda request: httpx.Response(200, text="<html>"))
    with pytest.raises(ProviderError, match="not JSON"):
        client.get_json("/x")


def test_error_messages_never_contain_the_api_key() -> None:
    client = make_client(lambda request: httpx.Response(500))
    with pytest.raises(ProviderError) as info:
        client.get_json("/find", {"api_key": "SECRET123", "domain": "a.com"})
    assert "SECRET123" not in str(info.value)
