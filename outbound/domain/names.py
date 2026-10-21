"""Small text helpers for people and company names. Pure functions, shared by every layer."""

from __future__ import annotations

import re
import unicodedata


def split_person(cell: str) -> tuple[str, str]:
    """``"Jack Kelly\\n(Co-Founder)"`` becomes (name, title)."""
    lines = [line.strip() for line in cell.splitlines() if line.strip()]
    if not lines:
        return "", ""
    title = " ".join(lines[1:])
    match = re.fullmatch(r"\((.*)\)", title)
    return lines[0], (match.group(1).strip() if match else title)


def split_name(full_name: str) -> tuple[str | None, str | None]:
    """First name and the rest; either may be None."""
    parts = full_name.split()
    if not parts:
        return None, None
    return parts[0], " ".join(parts[1:]) or None


def _plain(name: str) -> list[str]:
    decomposed = unicodedata.normalize("NFKD", name.casefold())
    letters = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.findall(r"[^\W_]+", letters)


def same_person(a: str | None, b: str | None) -> bool:
    """Whether two names at one company are the same person.

    Case and accents are ignored, and a first name alone matches a full name that starts with
    it ("Romain" and "Romain Serres"), since that is how a person is often added first.
    """
    left, right = _plain(a or ""), _plain(b or "")
    if not left or not right:
        return False
    if left == right:
        return True
    shorter, longer = sorted((left, right), key=len)
    return len(shorter) == 1 and shorter[0] == longer[0]


# Words that say what kind of company it is rather than which one.
COMPANY_NOISE = frozenset(
    {"ltd", "limited", "llc", "inc", "incorporated", "gmbh", "plc", "co", "company", "corp",
     "corporation", "the", "group", "holdings", "sa", "bv", "ag", "llp", "and"}
)  # fmt: skip


def company_tokens(name: str) -> list[str]:
    """The words that identify a company: lower case, no accents, no Ltd, Inc, Group..."""
    return [t for t in _plain(name) if t not in COMPANY_NOISE]


def domain_label(domain: str) -> str:
    """``"tilt-energy.com"`` becomes ``"tiltenergy"``: the name part of a website."""
    return domain.lower().split(".")[0].replace("-", "")


def employer_matches(employer: str, company: str, domain: str) -> bool:
    """Whether a profile's employer is this company: all of its name, or its website's name.

    One shared word is never enough ("Grid", "Power" and "Energy" are in many names).
    """
    words = company_tokens(employer)
    if not words:
        return False
    wanted = company_tokens(company)
    if wanted and all(word in words for word in wanted):
        return True
    label = domain_label(domain)
    return len(label) >= 3 and (label in words or label == "".join(words))


def mentions_company(text: str, company: str, domain: str) -> bool:
    """Whether some text names the company (its whole name, or its website's name)."""
    words = _plain(text)
    wanted = company_tokens(company)
    if wanted and all(word in words for word in wanted):
        return True
    label = domain_label(domain)
    return len(label) >= 3 and label in words


def clean_person_name(name: str) -> str:
    """A name as a person would write it: no emoji, symbols or stray punctuation."""
    kept = "".join(ch if ch.isalpha() or ch in " -'." else " " for ch in name)
    return " ".join(kept.replace(" .", " ").split()).strip(" .-'")


def read_profile_title(title: str) -> tuple[str, str, str]:
    """A LinkedIn result title becomes (name, job title, employer); unknown parts are empty.

    ``"Jane Doe - CTO - Acme Energy | LinkedIn"`` gives all three. ``"Jane Doe - CTO at Acme"``
    gives the same from a headline. A headline with no employer in it (``"Jane Doe - The Grid
    Needs More Innovators"``) is kept as the title, and the employer is left empty rather than
    guessed from it.
    """
    body = re.sub(r"\s*[|\-\u2013]\s*LinkedIn\s*$", "", title.strip(), flags=re.IGNORECASE)
    parts = [p.strip() for p in re.split(r"\s+[-\u2013]\s+", body) if p.strip()]
    if not parts:
        return "", "", ""
    name = clean_person_name(parts[0])
    if len(parts) >= 3:
        return name, parts[1], parts[-1]
    if len(parts) == 2:
        headline = parts[1]
        at = re.search(r"\s(?:at|@)\s+(.+)$", headline, flags=re.IGNORECASE)
        if at:
            employer = re.split(r"\s*[|,;]\s*", at.group(1))[0].rstrip(" .")
            return name, headline[: at.start()].strip(" ,|"), employer
        return name, headline, ""
    return name, "", ""


def display_name(name: str | None, domain: str) -> str:
    """What to call a company: its name if we have one, else the first label of its domain."""
    return name or domain.split(".")[0].title()
