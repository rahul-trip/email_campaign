"""One place for timeouts, retries and error mapping, shared by every adapter.

Retries happen only for network errors, 429 and 5xx. Other 4xx answers are our bug or a
bad key and fail at once. Exception messages carry the provider, status and path only,
never the URL, because several vendors take the API key as a query parameter.
"""

from __future__ import annotations

import threading
from typing import Any

import httpx
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)
from tenacity.wait import wait_base

from outbound.logging import get_logger
from outbound.providers.errors import ProviderAuthError, ProviderError, RateLimited

log = get_logger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30.0  # real-time verifiers can take 20s or more on slow servers
DEFAULT_ATTEMPTS = 3
_DEFAULT_WAIT: wait_base = wait_exponential(multiplier=1, min=1, max=8)


def require_api_key(provider: str, api_key: str) -> str:
    """Fail at construction, not at the first call, when a key is missing."""
    if not api_key or not api_key.strip():
        raise ProviderAuthError(provider, "API key is not set")
    return api_key.strip()


MAX_RETRY_AFTER_SECONDS = 60.0


def _honouring_retry_after(base: wait_base) -> wait_base:
    """After a 429, wait as long as the vendor asked (up to a minute); else the usual back-off."""

    class _Wait(wait_base):
        def __call__(self, retry_state: RetryCallState) -> float:
            outcome = retry_state.outcome
            error = outcome.exception() if outcome is not None else None
            if isinstance(error, RateLimited) and error.retry_after is not None:
                return min(error.retry_after, MAX_RETRY_AFTER_SECONDS)
            return base(retry_state)

    return _Wait()


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, ProviderError) and exc.retryable


# Calls in flight to one vendor at once, across every worker thread. The keys are shared by
# every workspace, and research fans out four ways, so without a cap K worker threads could
# send 4K requests together and trip the vendor's rate limit for everyone.
MAX_CONCURRENT_PER_PROVIDER = 4
_in_flight: dict[str, threading.BoundedSemaphore] = {}
_in_flight_lock = threading.Lock()


def _gate(provider: str) -> threading.BoundedSemaphore:
    with _in_flight_lock:
        gate = _in_flight.get(provider)
        if gate is None:
            gate = _in_flight[provider] = threading.BoundedSemaphore(MAX_CONCURRENT_PER_PROVIDER)
        return gate


class HttpClient:
    def __init__(
        self,
        provider: str,
        base_url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        attempts: int = DEFAULT_ATTEMPTS,
        wait: wait_base | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._provider = provider
        self._attempts = attempts
        self._wait = wait if wait is not None else _DEFAULT_WAIT
        self._client = client or httpx.Client(timeout=timeout)
        self._base_url = base_url.rstrip("/")
        self._headers = headers or {}

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._request("GET", path, params=params)

    def post_json(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return self._request("POST", path, json=body)

    def get_object(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Like ``get_json`` but the answer must be a JSON object, as every adapter assumes."""
        return self._object("GET", path, self._request("GET", path, params=params))

    def post_object(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._object("POST", path, self._request("POST", path, json=body))

    def _object(self, method: str, path: str, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProviderError(
                self._provider,
                f"{method} {path}: expected a JSON object, got {type(payload).__name__}",
            )
        return payload

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        retrying = Retrying(
            retry=retry_if_exception(_is_retryable),
            stop=stop_after_attempt(self._attempts),
            wait=_honouring_retry_after(self._wait),
            before_sleep=lambda state: self._log_retry(state, method, path),
            reraise=True,
        )
        return retrying(self._once, method, path, **kwargs)

    def _log_retry(self, state: RetryCallState, method: str, path: str) -> None:
        error = state.outcome.exception() if state.outcome else None
        log.warning(
            "provider_retry",
            provider=self._provider,
            request=f"{method} {path}",
            attempt=state.attempt_number,
            max_attempts=self._attempts,
            wait_seconds=round(state.next_action.sleep, 1) if state.next_action else None,
            reason=str(error)[:200],
            status_code=getattr(error, "status_code", None),
        )

    def _once(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self._base_url}/{path.lstrip('/')}"
        try:
            with _gate(self._provider):  # held for the request only, never across a retry wait
                response = self._client.request(method, url, headers=self._headers, **kwargs)
        except httpx.TransportError as exc:
            raise ProviderError(
                self._provider, f"{method} {path}: {type(exc).__name__}", retryable=True
            ) from None
        return self._interpret(method, path, response)

    def _interpret(self, method: str, path: str, response: httpx.Response) -> Any:
        status = response.status_code
        where = f"{method} {path}"
        if status == 429:
            retry_after = response.headers.get("retry-after")
            raise RateLimited(
                self._provider,
                f"{where}: 429",
                retry_after=float(retry_after) if retry_after and retry_after.isdigit() else None,
            )
        if status in (401, 403):
            raise ProviderAuthError(self._provider, f"{where}: {status}", status_code=status)
        if status == 202:  # accepted but not finished (Hunter's verifier); ask again
            raise ProviderError(
                self._provider, f"{where}: still processing", status_code=status, retryable=True
            )
        if status >= 500:
            raise ProviderError(
                self._provider, f"{where}: {status}", status_code=status, retryable=True
            )
        if status >= 400:
            raise ProviderError(self._provider, f"{where}: {status}", status_code=status)
        try:
            return response.json()
        except ValueError:
            raise ProviderError(
                self._provider, f"{where}: response was not JSON", status_code=status
            ) from None
