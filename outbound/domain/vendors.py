"""The third-party services the platform pays for, and how their settings are named (Phase 6d.4).

Pure data: which vendor owns which key, and how a key is shown (never in full)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Vendor:
    code: str
    name: str
    setting: str  # the ``Settings`` field that holds its key
    role: str  # what it does: llm, search, finder, verifier, resolver, registry


VENDORS: tuple[Vendor, ...] = (
    Vendor("llm", "Language model", "llm_api_key", "llm"),
    Vendor("tavily", "Tavily", "tavily_api_key", "search"),
    Vendor("hunter", "Hunter", "hunter_api_key", "finder"),
    Vendor("zerobounce", "ZeroBounce", "zerobounce_api_key", "finder"),
    Vendor("orbisearch", "OrbiSearch", "orbisearch_api_key", "verifier"),
    Vendor("myemailverifier", "MyEmailVerifier", "myemailverifier_api_key", "verifier"),
    Vendor("scrubby", "Scrubby", "scrubby_api_key", "resolver"),
    Vendor("enrichley", "Enrichley", "enrichley_api_key", "resolver"),
    Vendor("companies_house", "Companies House", "companies_house_api_key", "registry"),
)
BY_CODE: dict[str, Vendor] = {v.code: v for v in VENDORS}

# The language-model settings an admin may change without a deploy, and their types.
LLM_FIELDS: dict[str, type] = {
    "llm_provider": str,
    "llm_model": str,
    "llm_base_url": str,
    "llm_copy_model": str,
    "llm_temperature": float,
    "llm_max_tokens": int,
}

RETIRED_KEPT_DAYS = 30


def mask(last4: str) -> str:
    """How a key is shown anywhere but the explicit reveal."""
    return f"••••{last4}" if last4 else "not set"
