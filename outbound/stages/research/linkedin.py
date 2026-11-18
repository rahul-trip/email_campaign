"""Finding a person's LinkedIn profile address with a public search; profiles are never fetched.

One search per person, best effort. An address is kept only when the profile names the same
person (same surname, a matching or near-identical first name) *and* names this company (its
employer is the company, or its headline or snippet mentions it), so a namesake is never
attached to a lead. No link is better than a wrong one.
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit

from outbound.domain.names import mentions_company, read_profile_title, search_name
from outbound.domain.placement import Placed, Placement, place_by_rules, without_name
from outbound.providers.errors import ProviderError
from outbound.providers.ports import SearchProvider


def _words(text: str) -> list[str]:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.findall(r"[a-z]+", plain.lower())


def profile_address(url: str) -> str | None:
    """``https://www.linkedin.com/in/<slug>``, from any LinkedIn profile link; else ``None``."""
    parts = urlsplit(url)
    host = parts.netloc.lower().split(":")[0]
    if not (host == "linkedin.com" or host.endswith(".linkedin.com")):
        return None
    segments = [s for s in parts.path.split("/") if s]
    if len(segments) < 2 or segments[0] != "in":
        return None
    return f"https://www.linkedin.com/in/{segments[1]}"


def same_name(headline_name: str, full_name: str) -> bool:
    """Both names have the same surname, and one first name begins the other ("Jon", "Jonathan"
    or an initial). Anything looser would attach a namesake ("Jane" and "John") to the lead."""
    a, b = _words(headline_name), _words(full_name)
    if len(a) < 2 or len(b) < 2 or a[-1] != b[-1]:
        return False
    return a[0].startswith(b[0]) or b[0].startswith(a[0])


def _distance(a: str, b: str) -> int:
    """How many letters to add, drop or change to turn ``a`` into ``b``."""
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def similar_name(headline_name: str, full_name: str) -> bool:
    """The same surname and a first name spelled almost the same ("Shridhar" and "Sridhar",
    "Mohammad" and "Mohammed"): one letter apart, two for a long name. Only good enough together
    with a profile that names the company (``names_the_company``)."""
    a, b = _words(headline_name), _words(full_name)
    if len(a) < 2 or len(b) < 2 or a[-1] != b[-1]:
        return False
    first, other = a[0], b[0]
    allowed = (
        2 if min(len(first), len(other)) >= 7 else 1 if min(len(first), len(other)) >= 4 else 0
    )
    return _distance(first, other) <= allowed


def names_the_company(
    placed: Placed, *, full_name: str, headline: str, employer: str, snippet: str,
    company_name: str, domain: str,
) -> bool:  # fmt: skip
    """Whether the profile itself ties the person to this company: its employer is the
    company, or its headline or snippet mentions the company's name or website. A profile that
    says nothing about where they work is not taken (a common name has many namesakes)."""
    if placed.placement is Placement.WORKS_HERE:
        return True
    if placed.placement is Placement.NOT_HERE:
        return False
    rest = without_name(f"{headline} {employer} {snippet}", full_name)
    return mentions_company(rest, company_name, domain)


NAMES_PER_SEARCH = 5  # one search asks for this many people at once ("A" OR "B" OR ...)


def find_linkedin(
    search: SearchProvider, full_name: str, company_name: str, domain: str
) -> str | None:
    """The profile address of ``full_name`` at this company, or ``None`` if none clearly fits."""
    return find_linkedin_many(search, [full_name], company_name, domain).get(full_name)


def find_linkedin_many(
    search: SearchProvider, names: list[str], company_name: str, domain: str
) -> dict[str, str]:
    """Profile addresses for several people at one company, a few names per search.

    A lead with ten people costs two searches, not ten. A hit is kept for a name only when it
    names the same person (``same_name``, or ``similar_name`` for a one-letter spelling
    difference) and names this company (``names_the_company``); a name nobody clearly fits is
    left out (the lead page's button looks again).
    """
    # Profiles say "Daxa", not "Daxa inc": an exact phrase with Inc or Ltd finds no one.
    employer = search_name(company_name) or domain
    found: dict[str, str] = {}
    taken: set[str] = set()
    for start in range(0, len(names), NAMES_PER_SEARCH):
        chunk = names[start : start + NAMES_PER_SEARCH]
        people = " OR ".join(f'"{n}"' for n in chunk)
        query = (
            f'site:linkedin.com/in ({people}) "{employer}"'
            if len(chunk) > 1
            else (f'site:linkedin.com/in "{chunk[0]}" "{employer}"')
        )
        try:
            hits = search.search(query, max_results=min(20, 4 * len(chunk) + 1))
        except ProviderError:
            continue
        for hit in hits:
            address = profile_address(hit.url)
            if address is None or address in taken:
                continue
            name, headline, hit_employer = read_profile_title(hit.title)
            for full_name in chunk:
                if full_name in found:
                    continue
                if not (same_name(name, full_name) or similar_name(name, full_name)):
                    continue
                placed = place_by_rules(
                    name=full_name,
                    headline=headline,
                    employer=hit_employer,
                    snippet=hit.snippet,
                    company=company_name,
                    domain=domain,
                )
                if names_the_company(
                    placed, full_name=full_name, headline=headline, employer=hit_employer,
                    snippet=hit.snippet, company_name=company_name, domain=domain,
                ):  # fmt: skip
                    found[full_name] = address
                    taken.add(address)
                break
    return found
