"""Choosing what to search for when looking for new companies (Phase 6 follow-up).

The same search returns the same top companies, so a workspace that already has them gets
nothing new. Each run therefore searches from a new angle: a region, a kind of company, a
recent signal. This module has the rules that need no network: how queries are compared, and the
fallback angles used when no language model is available. The angles all start from the
campaign's own ideal-customer text, so they stay relevant to what the sender sells.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

# Angles that suit almost any seller, tried after the regions the sender says it serves.
SEGMENTS = (
    "mid-sized companies",
    "start-ups and scale-ups",
    "market leaders",
    "independent specialists",
    "that recently announced expansion or new projects",
    "that are hiring engineering or data teams",
    "family-owned and regional firms",
    "public sector and non-profit organisations",
)
MAX_QUERY_WORDS = 30


def normal(query: str) -> str:
    """A query as compared: lower case, words only, so spacing and punctuation do not matter."""
    return " ".join(re.findall(r"[a-z0-9]+", query.lower()))


def clean(queries: Iterable[object], *, used: Iterable[str], limit: int) -> list[str]:
    """The usable, new queries from a list a model wrote: strings, not empty, not too long, not
    one already run (or repeated within the list), at most ``limit`` of them."""
    seen = {normal(q) for q in used}
    out: list[str] = []
    for item in queries:
        if not isinstance(item, str):
            continue
        text = " ".join(item.split())
        key = normal(text)
        if not key or len(key.split()) > MAX_QUERY_WORDS or key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def regions(profile: Mapping[str, Any]) -> list[str]:
    """Where the sender says it sells, as separate places (``"UK, US and Germany"``)."""
    raw = str(profile.get("geographic_focus") or "")
    return [p.strip(" .") for p in re.split(r",|;|/|\band\b", raw) if p.strip(" .")]


def fallback_queries(
    base: str, profile: Mapping[str, Any], *, used: Iterable[str], limit: int
) -> list[str]:
    """New angles on ``base`` (the campaign's ideal-customer search), regions the sender serves
    first, then kinds of company. Used when no model is available, or it gave nothing usable."""
    angles = [f"in {region}" for region in regions(profile)] + list(SEGMENTS)
    return clean([f"{base} {angle}" for angle in angles], used=used, limit=limit)
