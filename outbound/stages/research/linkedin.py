"""Finding a person's LinkedIn profile address with a public search; profiles are never fetched.

One search per person, best effort: the address is only kept when the profile's headline names
the same person (same surname, matching first name), so a namesake is not attached to a lead.
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit

from outbound.domain.names import read_profile_title
from outbound.domain.placement import Placement, place_by_rules
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

    A lead with ten people costs two searches, not ten. A hit is kept for a name only when its
    headline names the same person and does not place them at another company; a name nobody
    clearly fits is left out (the lead page's button looks again).
    """
    employer = company_name.strip() or domain
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
                if full_name in found or not same_name(name, full_name):
                    continue
                placed = place_by_rules(
                    name=full_name,
                    headline=headline,
                    employer=hit_employer,
                    snippet=hit.snippet,
                    company=company_name,
                    domain=domain,
                )
                if placed.placement is not Placement.NOT_HERE:  # a namesake elsewhere is not them
                    found[full_name] = address
                    taken.add(address)
                break
    return found
