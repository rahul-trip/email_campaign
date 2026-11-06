"""Where to look for new companies, and how to tell what was found before (no I/O).

Discovery asks several sources (``plan_sources``): start-up directories when the brief is
after start-ups, and pages that list many companies, found by web search. When no model plans
the searches for such pages, they come from the brief's own words (``article_queries``). They
are compared by their words (``normal``, ``clean``) so no run repeats an earlier one, and a
company is recognised across sources by its name without its legal suffix (``name_key``).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from outbound.domain.brief import Brief, CompanyType

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


# --------------------------------------------------------------------------- sources

YC = "yc_directory"  # the public Y Combinator company directory
ARTICLES = "articles"  # lists, rankings and round-ups found by web search, read by a model
SOURCE_ORDER = (YC, ARTICLES)  # structured indexes first: cheaper, and their data is cleaner
STARTUP_SOURCES = frozenset({YC})


def plan_sources(brief: Brief, *, available: Iterable[str]) -> list[str]:
    """Where to look this run: the sources that suit the brief, of those that are set up."""
    usable = set(available)
    if brief.company_type not in {CompanyType.STARTUP, CompanyType.ANY}:
        usable -= STARTUP_SOURCES
    return [source for source in SOURCE_ORDER if source in usable]


def article_queries(brief: Brief, *, used: Iterable[str], limit: int) -> list[str]:
    """Searches for pages that name many companies like the ones wanted, built from the brief:
    what they do, the kind of company and where ("energy forecasting start-ups in Europe"), then
    the same with a kind of list page ("funding round-ups energy forecasting start-ups")."""
    keywords = brief.keywords or brief.segments
    segments = brief.segments if brief.keywords else ()
    kinds = segments or ("companies",)
    places = brief.regions or ("",)
    plain = [
        " ".join(f"{keyword} {kind} {'in ' + place if place else ''}".split())
        for keyword in keywords
        for place in places
        for kind in kinds
    ]
    lists = [f"{hint} {keyword} {kinds[0]}" for hint in brief.source_hints for keyword in keywords]
    return clean([*plain, *lists], used=used, limit=limit)


_SUFFIXES = re.compile(
    r"\b(ltd|limited|inc|incorporated|llc|plc|gmbh|ag|sa|sas|bv|nv|oy|ab|as|co|corp|"
    r"corporation|company|pty|srl|spa)\b\.?$"
)


def name_key(name: str) -> str:
    """A company's name as compared: lower case, "&" as "and", no punctuation and no legal
    suffix, so "Acme Energy Ltd." and "ACME energy" are the same company."""
    text = " ".join(re.findall(r"[a-z0-9]+", name.lower().replace("&", " and ")))
    while True:
        shorter = _SUFFIXES.sub("", text).strip()
        if shorter == text or not shorter:
            return text
        text = shorter
