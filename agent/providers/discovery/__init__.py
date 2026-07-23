"""agent/providers/discovery/__init__.py — Factory / Registry for discovery providers.

Factory pattern: callers ask for a provider by name; the registry maps names
to classes. Adding a new source = adding one entry here, zero edits elsewhere.

"tavily" is the default (see config.example.yaml) — set providers.discovery
back to "google_cse" in config.yaml to switch to Google Custom Search instead.
"""

from __future__ import annotations

from .base import CompanyDiscoveryProvider, ProviderError
from .google_cse import GoogleCseDiscoveryProvider
from .tavily import TavilyDiscoveryProvider

_REGISTRY: dict[str, type[CompanyDiscoveryProvider]] = {
    "tavily": TavilyDiscoveryProvider,
    "google_cse": GoogleCseDiscoveryProvider,
}


def get_discovery_provider(
    name: str,
    *,
    api_key: str = "",
    cx: str = "",
    per_call_delay_seconds: float = 1.0,
) -> CompanyDiscoveryProvider:
    """Return the concrete discovery provider for *name*.

    Args:
        name: Registry key ("tavily" or "google_cse").
        api_key: Provider-specific API key (TAVILY_API_KEY or GOOGLE_CSE_KEY —
            bundle.py picks the right one based on *name*).
        cx: Google CSE engine ID (only used by google_cse).
        per_call_delay_seconds: Politeness delay between HTTP calls.

    Raises:
        ProviderError: if *name* is not in the registry.
    """
    cls = _REGISTRY.get(name)
    if cls is None:
        available = list(_REGISTRY.keys())
        raise ProviderError(
            f"Unknown discovery provider {name!r}. Available: {available}"
        )
    if cls is GoogleCseDiscoveryProvider:
        return cls(api_key=api_key, cx=cx, per_call_delay_seconds=per_call_delay_seconds)
    if cls is TavilyDiscoveryProvider:
        return cls(api_key=api_key, per_call_delay_seconds=per_call_delay_seconds)
    return cls()  # type: ignore[call-arg]


__all__ = [
    "CompanyDiscoveryProvider",
    "ProviderError",
    "get_discovery_provider",
]
