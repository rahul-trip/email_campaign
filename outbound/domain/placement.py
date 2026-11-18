"""Does a person a search found work at the company? Free rules; no I/O.

A search for ``"Coval" CTO`` finds people *named* Coval, pages called "Aiir Consulting", and
people at "Five Iron Golf" when the company is "Golf". The rules place the clear cases and
leave the rest ``UNSURE`` for a model to judge from the profile's headline (or for the operator).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from outbound.domain.names import _plain, company_tokens, domain_label


class Placement(StrEnum):
    WORKS_HERE = "works_here"
    NOT_HERE = "not_here"
    UNSURE = "unsure"


@dataclass(frozen=True)
class Placed:
    placement: Placement
    reason: str


_PARENTHESES = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_AT = re.compile(r"\s(?:at|@)\s+(.+)$", re.IGNORECASE)


def _words(text: str) -> str:
    return " " + " ".join(_plain(text)) + " "


def without_name(text: str, name: str) -> str:
    """The text with the person's full name taken out, so their surname is not read as the
    company being mentioned ("Kristen Coval at Amazon" does not mention Coval)."""
    who = _plain(name)
    words = _plain(text)
    kept: list[str] = []
    i = 0
    while i < len(words):
        if who and words[i : i + len(who)] == who:
            i += len(who)
        else:
            kept.append(words[i])
            i += 1
    return " ".join(kept)


def _same_company(text: str, company: str, domain: str) -> bool:
    """Whether the text is this company and nothing more ("HyperProbe (YC S26)" is; "Five Iron
    Golf" is not "Golf")."""
    words = company_tokens(_PARENTHESES.sub(" ", text))
    if not words:
        return False
    wanted = company_tokens(company)
    if wanted and words == wanted:
        return True
    label = domain_label(domain)
    return len(label) >= 3 and (words == [label] or "".join(words) == label)


def _segments(headline: str) -> list[str]:
    """The parts of a headline that may name an employer: "Founder, Acme | Grid" -> Founder,
    Acme, Grid; "CTO at Acme" -> CTO, Acme."""
    found: list[str] = []
    for chunk in re.split(r"\s*[|,;/]\s*", headline):
        at = _AT.search(chunk)
        found.extend([chunk[: at.start()], at.group(1)] if at else [chunk])
    return [f.strip(" .") for f in found if f.strip(" .")]


def _overlaps(text: str, company: str, domain: str) -> bool:
    """Whether an employer could be this company: it holds all of the company's name ("Daxa AI"
    for "Daxa Inc"), or its website's name. One shared word is not enough: "Gapblue Software
    Labs" is not "Vibrant Labs"."""
    words = set(company_tokens(_PARENTHESES.sub(" ", text)))
    wanted = set(company_tokens(company))
    label = domain_label(domain)
    joined = "".join(company_tokens(text))
    return (bool(wanted) and wanted <= words) or (
        len(label) >= 3 and (label in words or label in joined)
    )


def place_by_rules(
    *,
    name: str,
    headline: str,
    employer: str,
    snippet: str,
    company: str,
    domain: str,
    site_text: str = "",
) -> Placed:
    """Place one person from a search result. ``headline`` is the profile's job title part;
    ``employer`` is what the result's title gave as the employer, if anything."""
    who = _plain(name)
    if len(who) >= 2 and " ".join(who) in _words(site_text):
        return Placed(Placement.WORKS_HERE, "named on the company's own site")
    for part in (employer, *_segments(headline)):
        if part and _same_company(part, company, domain):
            return Placed(Placement.WORKS_HERE, "their profile names this company")
    rest = without_name(f"{headline} {employer} {snippet}", name)
    wanted = company_tokens(company)
    label = domain_label(domain)
    in_name = bool(wanted) and all(w in who for w in wanted)
    in_name = in_name or (len(label) >= 3 and label in who)
    mentioned = bool(wanted) and all(w in rest.split() for w in wanted)
    mentioned = mentioned or (len(label) >= 3 and label in rest.split())
    if in_name and not mentioned:
        return Placed(
            Placement.NOT_HERE,
            "their own name matches the company's, nothing says they work there",
        )
    if employer and not mentioned and not _overlaps(employer, company, domain):
        return Placed(Placement.NOT_HERE, f"their profile says they work at {employer.strip()}")
    return Placed(Placement.UNSURE, "the profile does not clearly say where they work")
