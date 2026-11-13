"""Where to look for new companies, and how to tell what was found before (no I/O).

Discovery asks several sources (``plan_sources``): start-up directories when the brief is
after start-ups, the UK register for a UK brief with industry codes, lookalike search, and
pages that list many companies, found by web search. Sources whose leads qualify more often
are asked first and for more (``share``). When no model plans
the searches for such pages, they come from the brief's own words (``article_queries``). They
are compared by their words (``normal``, ``clean``) so no run repeats an earlier one, and a
company is recognised across sources by its name without its legal suffix (``name_key``).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from outbound.domain.brief import Brief, CompanyType
from outbound.domain.domains import is_free_mail, is_platform, registrable_domain
from outbound.domain.enums import CompanyStatus
from outbound.domain.names import company_tokens, domain_label

MAX_QUERY_WORDS = 30
MIN_NAME_LETTERS = 3  # a shorter name is too common to match a domain by


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
CH = "companies_house"  # the UK register, searched by industry (SIC) code
EXA = "exa"  # neural company search and lookalikes of example customers
ARTICLES = "articles"  # lists, rankings and round-ups found by web search, read by a model
# Structured indexes first: cheaper, and their data is cleaner.
SOURCE_ORDER = (YC, CH, EXA, ARTICLES)
STARTUP_SOURCES = frozenset({YC})
UK_PLACES = frozenset(
    {"uk", "gb", "united kingdom", "great britain", "britain", "england", "scotland", "wales",
     "northern ireland"}
)  # fmt: skip
# A lead past the fit gate, whatever became of it after.
QUALIFIED = frozenset(
    {CompanyStatus.QUALIFIED, CompanyStatus.CONTACTS_FOUND, CompanyStatus.EMAIL_READY,
     CompanyStatus.COPY_READY, CompanyStatus.APPROVED, CompanyStatus.REJECTED,
     CompanyStatus.IN_SEQUENCE, CompanyStatus.REPLIED, CompanyStatus.COMPLETED}
)  # fmt: skip
YIELD_DAYS = 90  # how far back a source's record counts
MIN_HISTORY = 10  # candidates a source must have found before its yield counts
MIN_SHARE, MAX_SHARE = 0.5, 2.0


@dataclass(frozen=True)
class SourceYield:
    """What one source found for a workspace, and how many of those leads qualified."""

    found: int  # companies it named (screened or not)
    qualified: int  # of those, leads that passed the fit gate
    leads: int = 0  # of those, how many became leads

    @property
    def rate(self) -> float:
        return self.qualified / self.found if self.found else 0.0


def is_uk(places: Iterable[str]) -> bool:
    return any(re.sub(r"^the ", "", p.strip().lower()) in UK_PLACES for p in places)


def _rates(yields: Mapping[str, SourceYield]) -> dict[str, float]:
    return {name: y.rate for name, y in yields.items() if y.found >= MIN_HISTORY}


def plan_sources(
    brief: Brief, *, available: Iterable[str], yields: Mapping[str, SourceYield] | None = None
) -> list[str]:
    """Where to look this run: the sources that suit the brief, of those that are set up, the
    ones whose leads have qualified most often first. A source with too little history counts
    as average, so a new one is tried without jumping the queue."""
    usable = set(available)
    if brief.company_type not in {CompanyType.STARTUP, CompanyType.ANY}:
        usable -= STARTUP_SOURCES
    if not (brief.industry_codes and is_uk(brief.regions)):
        usable.discard(CH)
    order = [source for source in SOURCE_ORDER if source in usable]
    rates = _rates(yields or {})
    if not rates:
        return order
    average = sum(rates.values()) / len(rates)
    return sorted(order, key=lambda s: -rates.get(s, average))  # stable: ties keep the order


def share(source: str, yields: Mapping[str, SourceYield]) -> float:
    """How much of the usual amount to ask of a source: its qualified rate against the
    average, between half and double; 1 while too little is known."""
    rates = _rates(yields)
    if source not in rates:
        return 1.0
    average = sum(rates.values()) / len(rates)
    if not average:
        return 1.0
    return max(MIN_SHARE, min(MAX_SHARE, rates[source] / average))


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
    """A company's name as compared: lower case, accents folded, "&" as "and", no punctuation
    and no legal suffix, so "Acme Energy Ltd." and "ACME energy" are the same company. A name
    in a script without Latin letters gives ""."""
    folded = unicodedata.normalize("NFKD", name.lower()).encode("ascii", "ignore").decode()
    text = " ".join(re.findall(r"[a-z0-9]+", folded.replace("&", " and ")))
    while True:
        shorter = _SUFFIXES.sub("", text).strip()
        if shorter == text or not shorter:
            return text
        text = shorter


def website_from_links(name: str, page_url: str, links: Iterable[tuple[str, str]]) -> str | None:
    """A company's own website, from the links on the page that named it (``(words, address)``
    pairs), when one is clear. A link counts when its domain *is* the company's name
    (``fingrid.fi`` for Fingrid), or when it says the company's name and goes to the site's front
    page (``Austrian Power Grid`` to ``apg.at/``). Links back to the page's own site, to
    platforms and to free mail never count, nor does a name two different sites both claim."""
    wanted = company_tokens(name)
    if not wanted:
        return None
    joined = "".join(wanted)
    if len(joined) < MIN_NAME_LETTERS:
        return None  # "E" is the label of e.org, and of a hundred other things
    own = registrable_domain(page_url)
    exact: dict[str, None] = {}
    front: dict[str, None] = {}
    for words, address in links:
        domain = registrable_domain(address)
        if not domain or domain == own or is_platform(domain) or is_free_mail(domain):
            continue
        if joined in (domain_label(domain), domain.replace(".", "").replace("-", "")):
            exact[domain] = None
            continue
        path = address.split("//", 1)[-1].partition("/")[2].split("?")[0].split("#")[0]
        if not path.strip("/") and name_key(words) == name_key(name):
            front[domain] = None
    for found in (exact, front):
        if len(found) == 1:
            return next(iter(found))
        if len(found) > 1:
            return None  # two sites claim the name: not clear enough to take
    return None
