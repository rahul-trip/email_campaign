"""Tavily: web search and page extraction.

Docs: https://docs.tavily.com/documentation/api-reference/endpoint/search and ``.../extract``

Moved up from the legacy ``agent/providers/discovery/tavily.py``. One basic search costs 1
credit; extraction costs 1 credit per 5 pages. Tavily answers 432 or 433 when the key's plan
or pay-as-you-go limit is exhausted, which is reported as ``BudgetExceeded``.
"""

from __future__ import annotations

from typing import Any

import httpx

from outbound.providers.errors import BudgetExceeded, ProviderError
from outbound.providers.http import HttpClient, require_api_key
from outbound.providers.ports import PageText, SearchHit

BASE_URL = "https://api.tavily.com"
_MAX_RESULTS = 20  # per search
_MAX_EXTRACT_URLS = 20  # per extract request
_LIMIT_STATUSES = {432, 433}


class TavilySearch:
    name = "tavily"

    def __init__(self, api_key: str, *, client: httpx.Client | None = None) -> None:
        key = require_api_key(self.name, api_key)
        self._http = HttpClient(
            self.name, BASE_URL, headers={"Authorization": f"Bearer {key}"}, client=client
        )

    def search(self, query: str, *, max_results: int = 5) -> list[SearchHit]:
        body = {
            "query": query,
            "max_results": max(1, min(max_results, _MAX_RESULTS)),
            "search_depth": "basic",
        }
        payload = self._post("/search", body)
        return [
            SearchHit(
                url=item["url"],
                title=item.get("title") or "",
                snippet=item.get("content") or "",
                score=item.get("score"),
            )
            for item in payload.get("results", [])
            if item.get("url")
        ]

    def extract(self, urls: list[str]) -> list[PageText]:
        pages: list[PageText] = []
        for start in range(0, len(urls), _MAX_EXTRACT_URLS):
            batch = urls[start : start + _MAX_EXTRACT_URLS]
            payload = self._post("/extract", {"urls": batch, "format": "text"})
            pages.extend(
                PageText(url=item["url"], text=item.get("raw_content") or "")
                for item in payload.get("results", [])
                if item.get("url") and item.get("raw_content")
            )
        return pages

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            payload = self._http.post_object(path, body)
        except ProviderError as exc:
            if exc.status_code in _LIMIT_STATUSES:
                raise BudgetExceeded(
                    self.name, "vendor plan or pay-as-you-go limit reached"
                ) from exc
            raise
        if not isinstance(payload, dict):
            raise ProviderError(self.name, f"POST {path}: unexpected response shape")
        return payload
