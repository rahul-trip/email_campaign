"""agent/providers/discovery/google_cse.py — Google Custom Search adapter.

Adapter pattern: wraps the Google Custom Search JSON API v1 and maps its
response into our Company domain objects. The rest of the codebase never sees
Google's JSON schema.

API docs: https://developers.google.com/custom-search/v1/using_rest
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

_CSE_URL = "https://www.googleapis.com/customsearch/v1"


class GoogleCseDiscoveryProvider(CompanyDiscoveryProvider):
    """Discovers companies via Google Custom Search JSON API.

    Adapter note:
        - Builds the query from keywords + location.
        - Paginates in 10-result batches until *limit* is reached.
        - Deduplicates by root domain.
        - Filters blocklisted domains.
        - Uses tenacity for retry/backoff on network / 5xx / 429 errors.
    """

    def __init__(self, api_key: str, cx: str, per_call_delay_seconds: float = 1.0) -> None:
        if not api_key:
            raise ProviderError("GOOGLE_CSE_KEY is not set.")
        if not cx:
            raise ProviderError("GOOGLE_CSE_CX is not set.")
        self._api_key = api_key
        self._cx = cx
        self._delay = per_call_delay_seconds

    def discover(self, keywords: list[str], location: str, limit: int) -> list[Company]:
        query = " ".join(keywords) + " " + location
        logger.debug("GoogleCse.discover query=%r limit=%d", query, limit)

        companies: list[Company] = []
        seen_domains: set[str] = set()
        start = 1  # Google CSE uses 1-indexed start param

        while len(companies) < limit:
            batch = self._fetch_page(query, start)
            if not batch:
                break
            for item in batch:
                domain = extract_domain(item.get("link", ""))
                if not domain or domain in seen_domains or domain in DOMAIN_BLOCKLIST:
                    continue
                seen_domains.add(domain)
                companies.append(Company(
                    name=item.get("title", domain),
                    domain=domain,
                    url=item.get("link", f"https://{domain}"),
                    description=(item.get("snippet") or "")[:300],
                ))
                if len(companies) >= limit:
                    break
            start += 10
            if self._delay:
                time.sleep(self._delay)

        logger.debug("GoogleCse.discover found %d companies", len(companies))
        return companies[:limit]

    @retry(
        retry=retry_if_exception_type((requests.exceptions.ConnectionError,
                                       requests.exceptions.Timeout)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _fetch_page(self, query: str, start: int) -> list[dict]:
        params = {
            "key": self._api_key,
            "cx": self._cx,
            "q": query,
            "start": start,
            "num": 10,
        }
        try:
            resp = requests.get(_CSE_URL, params=params, timeout=15)
        except requests.exceptions.RequestException as exc:
            logger.warning("GoogleCse fetch error (start=%d): %s", start, exc)
            raise

        if resp.status_code == 429:
            logger.warning("GoogleCse rate-limited (429), retrying…")
            raise requests.exceptions.ConnectionError("429 rate limit")

        if resp.status_code >= 500:
            logger.warning("GoogleCse server error %d", resp.status_code)
            raise requests.exceptions.ConnectionError(f"HTTP {resp.status_code}")

        if not resp.ok:
            logger.warning("GoogleCse unexpected status %d: %s", resp.status_code, resp.text[:200])
            raise ProviderError(f"Google CSE returned HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        return data.get("items", [])
