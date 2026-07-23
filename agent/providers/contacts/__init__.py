"""agent/providers/contacts/__init__.py — Factory / Registry for contact providers.

"brightdata" is the default (see config.example.yaml) — set providers.contacts
back to "proxycurl" in config.yaml to switch to Proxycurl instead.
"""

from __future__ import annotations

from agent.providers.discovery.base import ProviderError
from .base import ContactResolutionProvider
from .brightdata import BrightDataContactProvider
from .proxycurl import ProxycurlContactProvider

_REGISTRY: dict[str, type[ContactResolutionProvider]] = {
    "brightdata": BrightDataContactProvider,
    "proxycurl": ProxycurlContactProvider,
}


def get_contact_provider(
    name: str,
    *,
    api_key: str = "",
    dataset_id: str = "",
    per_call_delay_seconds: float = 1.0,
) -> ContactResolutionProvider:
    """Return the concrete contact provider for *name*.

    Args:
        name: Registry key ("brightdata" or "proxycurl").
        api_key: Provider-specific API key (BRIGHTDATA_API_KEY or
            PROXYCURL_API_KEY — bundle.py picks the right one based on *name*).
        dataset_id: Bright Data dataset ID (only used by brightdata).
        per_call_delay_seconds: Politeness delay between HTTP calls.
    """
    cls = _REGISTRY.get(name)
    if cls is None:
        raise ProviderError(
            f"Unknown contact provider {name!r}. Available: {list(_REGISTRY.keys())}"
        )
    if cls is BrightDataContactProvider:
        return cls(api_key=api_key, dataset_id=dataset_id, per_call_delay_seconds=per_call_delay_seconds)
    return cls(api_key=api_key, per_call_delay_seconds=per_call_delay_seconds)


__all__ = ["ContactResolutionProvider", "get_contact_provider"]
