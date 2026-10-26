"""Finding a person's LinkedIn profile address with a public search; profiles are never fetched.

One search per person, best effort: the address is only kept when the profile's headline names
the same person (same surname, matching first name), so a namesake is not attached to a lead.
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit

from outbound.domain.names import read_profile_title
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


def find_linkedin(
    search: SearchProvider, full_name: str, company_name: str, domain: str
) -> str | None:
    """The profile address of ``full_name`` at this company, or ``None`` if none clearly fits."""
    employer = company_name.strip() or domain
    try:
        hits = search.search(f'site:linkedin.com/in "{full_name}" "{employer}"', max_results=5)
    except ProviderError:
        return None
    for hit in hits:
        address = profile_address(hit.url)
        if address is None:
            continue
        name, _title, _employer = read_profile_title(hit.title)
        if same_name(name, full_name):
            return address
    return None
