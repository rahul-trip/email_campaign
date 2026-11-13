"""Tavily: web search and page extraction.

Docs: https://docs.tavily.com/documentation/api-reference/endpoint/search and ``.../extract``

Moved up from the legacy ``agent/providers/discovery/tavily.py``. One basic search costs 1
credit; extraction costs 1 credit per 5 pages. Tavily answers 432 or 433 when the key's plan
or pay-as-you-go limit is exhausted, which is reported as ``BudgetExceeded``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from outbound.providers.errors import BudgetExceeded, ProviderError
from outbound.providers.http import HttpClient, require_api_key
from outbound.providers.ports import PageLink, PageText, SearchHit

BASE_URL = "https://api.tavily.com"
_MAX_RESULTS = 20  # per search
_MAX_EXTRACT_URLS = 20  # per extract request
_LIMIT_STATUSES = {432, 433}
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_ANY_LINK = re.compile(r"\[([^\]]+)\]\([^)\s]*(?:\s+\"[^\"]*\")?\)")  # relative ones too
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)(?:\s+\"[^\"]*\")?\)")


def _with_links(markdown: str) -> tuple[str, tuple[PageLink, ...]]:
    """A markdown page as plain words plus the links it holds: images dropped, each
    ``[words](address)`` kept as its words, and the pairs listed once each."""
    found: dict[tuple[str, str], None] = {}
    for match in _LINK.finditer(_IMAGE.sub("", markdown)):
        found[(" ".join(match.group(1).split()), match.group(2))] = None
    text = _ANY_LINK.sub(lambda m: m.group(1), _IMAGE.sub("", markdown))
    return text, tuple(PageLink(text=words, url=url) for words, url in found)


class TavilySearch:
    name = "tavily"

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.Client | None = None,
        today: Callable[[], date] = lambda: datetime.now(UTC).date(),
    ) -> None:
        self._today = today
        key = require_api_key(self.name, api_key)
        self._http = HttpClient(
            self.name, BASE_URL, headers={"Authorization": f"Bearer {key}"}, client=client
        )

    def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        topic: str = "general",
        days: int | None = None,
    ) -> list[SearchHit]:
        body: dict[str, Any] = {
            "query": query,
            "max_results": max(1, min(max_results, _MAX_RESULTS)),
            "search_depth": "basic",
        }
        if topic != "general":
            body["topic"] = topic  # "news" also makes every result carry its published_date
        if days:
            # Tavily filters by date range, not "last N days"; undated results are dropped.
            body["start_date"] = (self._today() - timedelta(days=days)).isoformat()
            body["filter_by_published_date"] = True
        payload = self._post("/search", body)
        return [
            SearchHit(
                url=item["url"],
                title=item.get("title") or "",
                snippet=item.get("content") or "",
                score=item.get("score"),
                published_date=item.get("published_date"),
            )
            for item in payload.get("results", [])
            if item.get("url")
        ]

    def extract(self, urls: list[str], *, links: bool = False) -> list[PageText]:
        pages: list[PageText] = []
        for start in range(0, len(urls), _MAX_EXTRACT_URLS):
            batch = urls[start : start + _MAX_EXTRACT_URLS]
            # Plain text has no links; markdown keeps them, and only asking for it costs the
            # same credit.
            body = {"urls": batch, "format": "markdown" if links else "text"}
            payload = self._post("/extract", body)
            for item in payload.get("results", []):
                content = item.get("raw_content")
                if not item.get("url") or not content:
                    continue
                if links:
                    text, found = _with_links(content)
                    pages.append(PageText(url=item["url"], text=text, links=found))
                else:
                    pages.append(PageText(url=item["url"], text=content))
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
