"""agent/providers/discovery/tavily.py — Tavily Search adapter.

Adapter pattern: wraps the Tavily Search API and maps its response into our
Company domain objects. The rest of the codebase never sees Tavily's JSON
schema.

API docs: https://docs.tavily.com/documentation/api-reference/endpoint/search
"""

from __future__ import annotations

import logging
import time

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from agent.domain.models import Company
from ._common import DOMAIN_BLOCKLIST, extract_domain
from .base import CompanyDiscoveryProvider, ProviderError

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://api.tavily.com/search"
_MAX_RESULTS_PER_CALL = 20  # Tavily's per-request cap on max_results


class TavilyDiscoveryProvider(CompanyDiscoveryProvider):
    """Discovers companies via the Tavily Search API.

    Adapter note:
        - Builds the query from keywords + location.
        - Tavily has no offset/pagination parameter — unlike Google CSE, a
          single call is all we get. If *limit* exceeds Tavily's own
          per-request cap (_MAX_RESULTS_PER_CALL), only the cap's worth is
          requested and a warning is logged.
        - Deduplicates by root domain, filters blocklisted domains (shared
          with google_cse.py via _common.py).
        - Uses tenacity for retry/backoff on network / 5xx / 429 errors.
    """

    def __init__(self, api_key: str, per_call_delay_seconds: float = 1.0) -> None:
        if not api_key:
            raise ProviderError("TAVILY_API_KEY is not set.")
        self._api_key = api_key
        self._delay = per_call_delay_seconds

    def discover(self, keywords: list[str], location: str, limit: int) -> list[Company]:
        query = " ".join(keywords) + " " + location
        logger.debug("Tavily.discover query=%r limit=%d", query, limit)

        requested = min(limit, _MAX_RESULTS_PER_CALL)
        if limit > _MAX_RESULTS_PER_CALL:
            logger.warning(
                "Tavily.discover: limit=%d exceeds Tavily's %d-result-per-call cap; "
                "only up to %d companies can be returned from a single search.",
                limit, _MAX_RESULTS_PER_CALL, _MAX_RESULTS_PER_CALL,
            )

        items = self._fetch_results(query, requested)
        if self._delay:
            time.sleep(self._delay)

        companies: list[Company] = []
        seen_domains: set[str] = set()
        for item in items:
            domain = extract_domain(item.get("url", ""))
            if not domain or domain in seen_domains or domain in DOMAIN_BLOCKLIST:
                continue
            seen_domains.add(domain)
            companies.append(Company(
                name=item.get("title", domain),
                domain=domain,
                url=item.get("url", f"https://{domain}"),
                description=(item.get("content") or "")[:300],
            ))
            if len(companies) >= limit:
                break

        logger.debug("Tavily.discover found %d companies", len(companies))
        return companies

    @retry(
        retry=retry_if_exception_type((requests.exceptions.ConnectionError,
                                       requests.exceptions.Timeout)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _fetch_results(self, query: str, max_results: int) -> list[dict]:
        body = {
            "api_key": self._api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
        }
        try:
            resp = requests.post(_SEARCH_URL, json=body, timeout=30)
        except requests.exceptions.RequestException as exc:
            logger.warning("Tavily fetch error: %s", exc)
            raise

        if resp.status_code == 429:
            logger.warning("Tavily rate-limited (429), retrying…")
            raise requests.exceptions.ConnectionError("429 rate limit")

        if resp.status_code >= 500:
            logger.warning("Tavily server error %d", resp.status_code)
            raise requests.exceptions.ConnectionError(f"HTTP {resp.status_code}")

        if not resp.ok:
            logger.warning("Tavily unexpected status %d: %s", resp.status_code, resp.text[:200])
            raise ProviderError(f"Tavily returned HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        return data.get("results", [])
