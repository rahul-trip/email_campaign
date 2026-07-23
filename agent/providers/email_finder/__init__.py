"""agent/providers/email_finder/__init__.py — Factory / Registry for email-finder providers."""

from __future__ import annotations

from agent.providers.discovery.base import ProviderError
from .base import EmailFinderProvider
from .hunter import HunterEmailFinder

_REGISTRY: dict[str, type[EmailFinderProvider]] = {
    "hunter": HunterEmailFinder,
}


def get_email_finder(
    name: str,
    *,
    api_key: str = "",
    per_call_delay_seconds: float = 1.0,
) -> EmailFinderProvider:
    """Return the concrete email-finder provider for *name*."""
    cls = _REGISTRY.get(name)
    if cls is None:
        raise ProviderError(
            f"Unknown email-finder provider {name!r}. Available: {list(_REGISTRY.keys())}"
        )
    return cls(api_key=api_key, per_call_delay_seconds=per_call_delay_seconds)


__all__ = ["EmailFinderProvider", "get_email_finder"]
