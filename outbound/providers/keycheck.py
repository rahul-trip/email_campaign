"""Checking that a vendor key works, with one small call (Phase 6d).

The console's Test button uses it. It asks each vendor for the least it can: a one-token model
reply, a one-result search, one address checked. That is a real call and costs a fraction of a
cent. Vendors whose calls are slow or unclear (the catch-all resolvers) are not tested here.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from outbound.config import Settings
from outbound.providers.errors import ProviderAuthError, ProviderError
from outbound.providers.ports import PersonQuery
from outbound.providers.registry import (
    build_company_registry,
    build_finder_named,
    build_llm,
    build_search,
    build_verifier_named,
)

VERIFIERS = ("hunter", "zerobounce", "orbisearch", "myemailverifier")
# Finders with no verifier of their own: tested by asking for a person who cannot be found,
# which none of them charges for.
FINDERS = ("anymailfinder", "prospeo", "icypeas", "generect")
WHAT = {
    "llm": "one very short model reply",
    "tavily": "one search for one result",
    "companies_house": "one company-name search",
    **dict.fromkeys(VERIFIERS, "one email address checked"),
    **dict.fromkeys(FINDERS, "one lookup that finds nothing, which is free"),
}


@dataclass(frozen=True)
class KeyCheck:
    ok: bool | None  # None: this vendor cannot be tested from here
    message: str


def can_test(vendor: str) -> bool:
    return vendor in WHAT


def check_key(vendor: str, settings: Settings, client: httpx.Client | None = None) -> KeyCheck:
    """Make the vendor's smallest call with the key in ``settings``."""
    if not can_test(vendor):
        return KeyCheck(None, "This vendor is tested by its first real use; it has no cheap check.")
    try:
        if vendor == "llm":
            # The model's own token limit: a reasoning model spends a small cap thinking.
            build_llm(settings, client).complete("Reply with the single word OK.", "ping")
        elif vendor == "tavily":
            build_search(settings, client).search("outbound key test", max_results=1)
        elif vendor == "companies_house":
            registry = build_company_registry(settings, client)
            if registry is None:
                return KeyCheck(False, "There is no key to test.")
            registry.search("Tesco", max_results=1)
        elif vendor in FINDERS:
            build_finder_named(vendor, settings, client).find(
                PersonQuery(first_name="Key", last_name="Test"), "example.com"
            )
        else:
            build_verifier_named(vendor, settings, client).verify("key-test@example.com")
    except ProviderAuthError:
        return KeyCheck(False, "The vendor rejected this key. Replace it with a working one.")
    except ProviderError as error:
        if "cut off at the token limit" in str(error):
            # The provider took the key and answered; only the reply ran long.
            return KeyCheck(
                True, f"The key works ({WHAT[vendor]}), but the reply hit the token limit."
            )
        return KeyCheck(False, f"The key was not confirmed: {str(error)[:200]}")
    return KeyCheck(True, f"The key works ({WHAT[vendor]}).")
