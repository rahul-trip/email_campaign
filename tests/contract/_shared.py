"""Behaviour every adapter must share, whatever its vendor, for failures and credentials."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from outbound.providers.errors import ProviderAuthError, ProviderError, RateLimited
from tests.providers.helpers import Handler, always

SECRET = "k-secret-123"


class AdapterContract:
    """Subclasses implement ``build`` and ``call`` and may override ``auth_failed``."""

    def build(self, handler: Handler, api_key: str = SECRET) -> Any:
        raise NotImplementedError

    def call(self, adapter: Any) -> Any:
        """Make one ordinary call that is expected to succeed."""
        raise NotImplementedError

    def ok_response(self) -> httpx.Response:
        raise NotImplementedError

    def auth_failed(self) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    def test_blank_api_key_is_rejected_at_construction(self) -> None:
        with pytest.raises(ProviderAuthError):
            self.build(always(self.ok_response()), api_key="")

    def test_rejected_key_raises_auth_error(self) -> None:
        with pytest.raises(ProviderAuthError):
            self.call(self.build(always(self.auth_failed())))

    def test_rate_limit_raises_rate_limited(self) -> None:
        with pytest.raises(RateLimited):
            self.call(self.build(always(httpx.Response(429))))

    def test_server_error_raises_a_retryable_provider_error(self) -> None:
        with pytest.raises(ProviderError) as info:
            self.call(self.build(always(httpx.Response(503))))
        assert info.value.retryable

    def test_sends_the_api_key(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return self.ok_response()

        self.call(self.build(handler))
        request = seen[0]
        carried = str(request.url) + str(dict(request.headers))
        assert SECRET in carried

    def test_failures_never_leak_the_api_key(self) -> None:
        with pytest.raises(ProviderError) as info:
            self.call(self.build(always(httpx.Response(500))))
        assert SECRET not in str(info.value)
