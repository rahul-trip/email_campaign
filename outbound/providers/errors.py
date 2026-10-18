"""Errors raised by provider adapters and the budget guard.

Stages catch ``ProviderError`` and decide whether to retry, skip or fail the lead.
Messages never contain request URLs, because several vendors take the API key as a
query parameter.
"""

from __future__ import annotations


class ProviderError(Exception):
    """A provider call failed. ``retryable`` is true for 429, 5xx and network errors."""

    def __init__(
        self,
        provider: str,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.status_code = status_code
        self.retryable = retryable


class ProviderAuthError(ProviderError):
    """The vendor rejected our credentials (401 or 403). Never retried: fix the key."""


class RateLimited(ProviderError):
    """The vendor answered 429. Retryable; ``retry_after`` is seconds when the vendor says."""

    def __init__(
        self, provider: str, message: str = "rate limited", *, retry_after: float | None = None
    ) -> None:
        super().__init__(provider, message, status_code=429, retryable=True)
        self.retry_after = retry_after


class BudgetExceeded(ProviderError):
    """A call was refused before it was made because it would break a spend cap."""

    def __init__(self, provider: str, message: str) -> None:
        super().__init__(provider, message, retryable=False)
