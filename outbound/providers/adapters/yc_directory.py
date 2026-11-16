"""The Y Combinator company directory, from the public yc-oss mirror.

Docs: https://github.com/yc-oss/api (rebuilt daily from YC's own directory; no key, no charge).

The whole directory is one JSON download of a few megabytes, so it is fetched once and kept in
memory for a day; each search filters it locally. A company matches when the query's words
(compared by stem) are among its industries and tags, or two of them in its one-liner and
description; inactive and acquired companies and sites already known are left out. Its YC page
is kept as the source; its batch, size, stage, place and tags are the evidence screening reads.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable
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
        """Live companies about the query's words, best match first, newest batch first among
        equals. Words are compared by stem ("utilities" finds "utility"), one by one: the
        brief's words are a description, not a phrase a company's text would repeat."""
        terms = _terms(query.keywords)
        if not terms:
            return []
        regions = [r.lower() for r in query.regions]
        skip = {d.lower() for d in query.exclude_domains}
        scored: list[tuple[int, tuple[int, int], int, dict[str, Any]]] = []
        for order, company in enumerate(self._directory()):
            if company.get("status") not in _LIVE:
                continue
            if skip and registrable_domain(str(company.get("website") or "")) in skip:
                continue
            if regions and not any(_in_place(r, _places(company)) for r in regions):
                continue
            founded = _founded(company)
            if query.founded_after and (founded is None or founded < query.founded_after):
                continue
            score = _score(terms, company)
            if score:
                scored.append((-score, _newest(company), order, company))
        scored.sort(key=lambda item: item[:3])
        return [_mention(company) for *_, company in scored[:limit]]

    def _directory(self) -> list[dict[str, Any]]:
        now = self._clock()
        if self._fetched_at is None or now - self._fetched_at > KEEP_SECONDS:
            payload = self._http.get_json("/companies/all.json")
            self._companies = [c for c in payload if isinstance(c, dict) and c.get("name")]
            self._fetched_at = now
        return self._companies


def _word(phrase: str, text: str) -> bool:
    """The phrase as whole words: "us" is in "us and canada", not in "russia"."""
    return re.search(rf"\b{re.escape(phrase)}\b", text) is not None


LABEL_HIT, TEXT_HIT = 3, 1  # a hit in the directory's own labels says more than one in prose


def _stem(word: str) -> str:
    """A word cut to its stem, enough to equate "utilities" and "utility", "grids" and "grid",
    "forecasting" and "forecast" (not a linguist's stemmer)."""
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("ing") and len(word) > 6:
        return word[:-3]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def _stems(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", text.lower())}


def _terms(keywords: Iterable[str]) -> list[str]:
    """The stems of every word in the keywords, once each."""
    seen: dict[str, None] = {}
    for keyword in keywords:
        for word in re.findall(r"[a-z0-9]+", keyword.lower()):
            if len(word) > 1:
                seen[_stem(word)] = None
    return list(seen)


def _score(terms: list[str], company: dict[str, Any]) -> int:
    """0 when the company is not about the terms. A term in its industries, sub-industry or
    tags is worth 3 and one in its one-liner or description 1. A company matches on a label
    hit, or on two different terms in its prose (one only, when only one was asked), which
    keeps "the power of biotech" out of a search for power."""
    labels = _stems(
        " ".join(
            [str(company.get("subindustry") or ""), *map(str, company.get("tags") or []),
             *map(str, company.get("industries") or [])]
        )
    )  # fmt: skip
    prose = _stems(f"{company.get('one_liner') or ''} {company.get('long_description') or ''}")
    in_labels = sum(t in labels for t in terms)
    in_prose = sum(t in prose for t in terms if t not in labels)
    if in_labels or in_prose >= min(2, len(terms)):
        return in_labels * LABEL_HIT + in_prose * TEXT_HIT
    return 0


_SEASONS = {"winter": 1, "spring": 2, "summer": 3, "fall": 4, "autumn": 4}


def _newest(company: dict[str, Any]) -> tuple[int, int]:
    """Sorts the newest batch first: (-year, -season)."""
    batch = str(company.get("batch") or "").lower()
    year = _founded(company) or 0
    season = next((n for name, n in _SEASONS.items() if name in batch), 0)
    if not season:
        season = {"w": 1, "s": 3, "f": 4}.get(batch[:1], 0)
    return (-year, -season)


# What a brief may call a place, and what the directory calls it.
_PLACE_NAMES = {
    "uk": ("united kingdom",), "gb": ("united kingdom",), "great britain": ("united kingdom",),
    "britain": ("united kingdom",), "england": ("united kingdom",),
    "us": ("united states",), "usa": ("united states",), "u.s.": ("united states",),
    "america": ("united states",), "eu": ("europe",),
}  # fmt: skip


def _in_place(region: str, places: str) -> bool:
    """A brief's region among a company's places, as whole words or by a common name
    ("UK" is "United Kingdom"; "US" is not in "Russia" or "Columbus")."""
    name = re.sub(r"^the ", "", region.strip().lower())
    return any(_word(n, places) for n in (name, *_PLACE_NAMES.get(name, ())))


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
        evidence=_evidence(company, batch, one_liner),
    )


def _evidence(company: dict[str, Any], batch: str, one_liner: str) -> str:
    """What the directory knows, in one line for screening: without the team size, stage and
    place the model could only say that the text does not establish size or geography."""
    facts = [
        f"{company['team_size']} people" if company.get("team_size") else "",
        f"{company['stage']} stage" if company.get("stage") else "",
        str(company.get("all_locations") or ""),
        ", ".join(str(t) for t in (company.get("tags") or [])[:6]),
        "hiring" if company.get("isHiring") else "",
    ]
    detail = "; ".join(f for f in facts if f)
    head = f"Y Combinator {batch}: {one_liner}".strip(": ")
    return f"{head}. {detail}" if detail else head
