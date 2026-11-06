"""The Y Combinator company directory, from the public yc-oss mirror.

Docs: https://github.com/yc-oss/api (rebuilt daily from YC's own directory; no key, no charge).

The whole directory is one JSON download of a few megabytes, so it is fetched once and kept in
memory for a day; each search filters it locally. A company matches when the query's keywords
appear in its one-liner, description, tags or industries; inactive and acquired companies are
left out. Its YC page is kept as the source, and its batch as the evidence.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any

import httpx

from outbound.domain.discovery import YC
from outbound.domain.domains import registrable_domain
from outbound.providers.http import HttpClient
from outbound.providers.ports import CompanyMention, SourceQuery

BASE_URL = "https://yc-oss.github.io/api"
KEEP_SECONDS = 24 * 3600
_LIVE = {"Active", "Public"}
_YEAR = re.compile(r"(\d{4})|\b[WSFX](\d{2})\b")


class YcDirectory:
    name = YC

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._http = HttpClient(self.name, BASE_URL, client=client)
        self._clock = clock
        self._companies: list[dict[str, Any]] = []
        self._fetched_at: float | None = None

    def find(self, query: SourceQuery, *, limit: int) -> list[CompanyMention]:
        words = [w.lower() for w in query.keywords if w.strip()]
        if not words:
            return []
        regions = [r.lower() for r in query.regions]
        scored: list[tuple[int, int, dict[str, Any]]] = []
        for order, company in enumerate(self._directory()):
            if company.get("status") not in _LIVE:
                continue
            if regions and not any(r in _places(company) for r in regions):
                continue
            founded = _founded(company)
            if query.founded_after and (founded is None or founded < query.founded_after):
                continue
            text = _text(company)
            score = sum(_matches(word, text) for word in words)
            if score:
                scored.append((-score, order, company))
        scored.sort(key=lambda item: item[:2])
        return [_mention(company) for _, _, company in scored[:limit]]

    def _directory(self) -> list[dict[str, Any]]:
        now = self._clock()
        if self._fetched_at is None or now - self._fetched_at > KEEP_SECONDS:
            payload = self._http.get_json("/companies/all.json")
            self._companies = [c for c in payload if isinstance(c, dict) and c.get("name")]
            self._fetched_at = now
        return self._companies


def _matches(phrase: str, text: str) -> int:
    """2 when the whole phrase appears, 1 when every word of it does, else 0."""
    if phrase in text:
        return 2
    return 1 if all(re.search(rf"\b{re.escape(w)}", text) for w in phrase.split()) else 0


def _text(company: dict[str, Any]) -> str:
    parts = [
        company.get("one_liner"),
        company.get("long_description"),
        company.get("subindustry"),
        *(company.get("tags") or []),
        *(company.get("industries") or []),
    ]
    return " ".join(str(p) for p in parts if p).lower()


def _places(company: dict[str, Any]) -> str:
    return " ".join(
        [str(company.get("all_locations") or ""), *map(str, company.get("regions") or [])]
    ).lower()


def _founded(company: dict[str, Any]) -> int | None:
    """The batch year ("Winter 2022" or "W22"), the nearest thing the directory has."""
    found = _YEAR.search(str(company.get("batch") or ""))
    if not found:
        return None
    return int(found.group(1)) if found.group(1) else 2000 + int(found.group(2))


def _mention(company: dict[str, Any]) -> CompanyMention:
    regions = [str(r) for r in company.get("regions") or []]
    batch = str(company.get("batch") or "")
    one_liner = str(company.get("one_liner") or "")
    return CompanyMention(
        name=str(company["name"]),
        domain=registrable_domain(str(company.get("website") or "")) or None,
        description=" ".join(
            p for p in (one_liner, str(company.get("long_description") or "")) if p
        )[:1_000],
        tags=tuple(str(t) for t in company.get("tags") or [])[:10],
        country=regions[0] if regions else "",
        founded=_founded(company),
        size=str(company.get("team_size") or ""),
        stage=str(company.get("stage") or ""),
        source=YC,
        source_url=str(company.get("url") or ""),
        evidence=f"Y Combinator {batch}: {one_liner}".strip(": "),
    )
