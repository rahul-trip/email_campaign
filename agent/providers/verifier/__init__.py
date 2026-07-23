"""agent/providers/verifier/__init__.py — Factory / Registry for verifier providers."""

from __future__ import annotations

from agent.providers.discovery.base import ProviderError
from .base import EmailVerifierProvider, VerificationStatus
from .neverbounce import NeverBounceVerifier

_REGISTRY: dict[str, type[EmailVerifierProvider]] = {
    "neverbounce": NeverBounceVerifier,
}


def get_verifier(
    name: str,
    *,
    api_key: str = "",
    per_call_delay_seconds: float = 1.0,
) -> EmailVerifierProvider:
    """Return the concrete email verifier for *name*."""
    cls = _REGISTRY.get(name)
    if cls is None:
        raise ProviderError(
            f"Unknown verifier provider {name!r}. Available: {list(_REGISTRY.keys())}"
        )
    return cls(api_key=api_key, per_call_delay_seconds=per_call_delay_seconds)


__all__ = ["EmailVerifierProvider", "VerificationStatus", "get_verifier"]
