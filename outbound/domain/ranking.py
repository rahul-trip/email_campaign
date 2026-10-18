"""Ordering a company's candidate contacts against the campaign's wanted job titles.

Simple on purpose: abbreviations are spelled out, a wanted title matches when all its words
appear in the person's title, and ties fall back to seniority. An operator-given person always
comes first, because the operator chose them.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from outbound.domain.entities import Contact
from outbound.domain.enums import ContactSource

_ABBREVIATIONS = {
    "ceo": "chief executive officer",
    "cto": "chief technology officer",
    "cfo": "chief financial officer",
    "coo": "chief operating officer",
    "cio": "chief information officer",
    "cmo": "chief marketing officer",
    "cpo": "chief product officer",
    "cro": "chief revenue officer",
    "svp": "senior vice president",
    "evp": "executive vice president",
    "vp": "vice president",
    "md": "managing director",
}

# Lower is more senior. The label is stored on the contact as ``seniority``.
_LEVELS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("vp", re.compile(r"\bvice president\b")),
    (
        "c_level",
        re.compile(r"\bchief\b|\bfounder\b|\bowner\b|\bpresident\b|managing director|\bpartner\b"),
    ),
    ("director", re.compile(r"\bdirector\b|\bhead of\b")),
    ("manager", re.compile(r"\bmanager\b|\blead\b")),
)
_FILLER = frozenset({"of", "the", "and", "for", "&", "at", "in"})
OTHER = "other"


def normalise_title(title: str) -> str:
    words = re.findall(r"[a-z0-9&]+", title.lower())
    return " ".join(_ABBREVIATIONS.get(word, word) for word in words)


def _words(title: str) -> set[str]:
    return set(normalise_title(title).split()) - _FILLER


def seniority_of(title: str | None) -> str:
    text = normalise_title(title or "")
    for label, pattern in _LEVELS:
        if pattern.search(text):
            return label
    return OTHER


def _level_index(label: str) -> int:
    labels = [name for name, _ in _LEVELS]
    return labels.index(label) if label in labels else len(labels)


def wanted_index(title: str | None, wanted: Sequence[str]) -> int:
    """Position of the first wanted title the person's title satisfies; ``len(wanted)`` if none."""
    text = _words(title or "")
    for index, target in enumerate(wanted):
        words = _words(target)
        if words and words <= text:
            return index
    return len(wanted)


@dataclass(frozen=True)
class RankedContact:
    contact: Contact
    rank: int
    seniority: str


def rank_contacts(contacts: Sequence[Contact], wanted_titles: Sequence[str]) -> list[RankedContact]:
    """Best first. Ranks are consecutive from 1."""

    def key(contact: Contact) -> tuple[int, int, int, int]:
        operator_first = 0 if contact.source is ContactSource.OPERATOR else 1
        return (
            operator_first,
            wanted_index(contact.title, wanted_titles),
            _level_index(seniority_of(contact.title)),
            contact.rank,
        )

    ordered = sorted(contacts, key=key)
    return [
        RankedContact(contact, position, seniority_of(contact.title))
        for position, contact in enumerate(ordered, start=1)
    ]
