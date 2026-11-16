"""Ordering a company's candidate contacts against the campaign's wanted job titles.

Simple on purpose: abbreviations are spelled out, a wanted title matches when all its words
appear in the person's title, and ties fall back to seniority. An operator-given person always
comes first, because the operator chose them.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence
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
# C-level comes before vice president (a "vice president" is not a "president").
_LEVELS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "c_level",
        re.compile(
            r"\bchief\b|\bfounder\b|\bowner\b|(?<!vice )\bpresident\b|managing director|\bpartner\b"
        ),
    ),
    ("vp", re.compile(r"\bvice president\b")),
    ("director", re.compile(r"\bdirector\b|\bhead of\b")),
    ("manager", re.compile(r"\bmanager\b|\blead\b")),
)
_FILLER = frozenset({"of", "the", "and", "for", "&", "at", "in"})
OTHER = "other"


def normalise_title(title: str) -> str:
    words = re.findall(r"[a-z0-9&]+", title.lower())
    return " ".join(_ABBREVIATIONS.get(word, word) for word in words)


# Nouns that make a phrase a job and not a kind of company ("BESS integrators", "VPP platforms").
_ROLE_NOUNS = frozenset(
    """chief officer president founder cofounder owner partner director head manager lead
    principal engineer developer analyst scientist architect consultant specialist trader
    strategist advisor adviser executive coordinator administrator controller planner buyer
    procurement""".split()  # noqa: SIM905 - a long word list reads better as text
)


def is_role(title: str) -> bool:
    """Whether a wanted "job title" names a job. A search for people titled "BESS
    integrators" finds nobody, so such an entry is flagged when a campaign is saved and left
    out of the people search."""
    words = normalise_title(title).split()
    return any(w in _ROLE_NOUNS or w.removesuffix("s") in _ROLE_NOUNS for w in words)


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


DECISION_LEVELS = frozenset({"c_level", "vp", "director"})


def is_decision_maker(title: str | None, wanted: Sequence[str] = ()) -> bool:
    """Whether a person can decide to buy: they hold one of the campaign's wanted titles, or are
    a founder, owner, C-level, vice president, director or head of. An engineer or a manager
    is not, and nobody without a title can be known to be."""
    if not (title or "").strip():
        return False
    return wanted_index(title, wanted) < len(wanted) or seniority_of(title) in DECISION_LEVELS


def can_be_written_to(
    contact: Contact,
    wanted: Sequence[str],
    chosen_ids: Collection[str] = (),
    *,
    first_counts: bool = False,
) -> bool:
    """Whether an email may be written to this person: a decision-maker, or someone the operator
    chose (added, gave an address or a consent for). With ``first_counts`` the person ranked
    first also counts: once a lead has been ranked, that is a decision-maker or a person the
    operator moved to the front ("write to someone else")."""
    return (
        contact.source is ContactSource.OPERATOR
        or contact.id in chosen_ids
        or (first_counts and contact.rank == 1)
        or is_decision_maker(contact.title, wanted)
    )


@dataclass(frozen=True)
class RankedContact:
    contact: Contact
    rank: int
    seniority: str


def rank_contacts(
    contacts: Sequence[Contact],
    wanted_titles: Sequence[str],
    chosen_ids: Collection[str] = (),
) -> list[RankedContact]:
    """Best first. Ranks are consecutive from 1.

    ``chosen_ids`` are people the operator picked without adding them: they gave an address
    or recorded a consent. Like a person the operator added, they come first, in the order the
    operator left them, so the email goes to the person whose consent or address it relies on.
    """

    def key(contact: Contact) -> tuple[int, int, int, int]:
        chosen = contact.source is ContactSource.OPERATOR or contact.id in chosen_ids
        if chosen:
            return (0, contact.rank, 0, 0)
        return (
            1,
            wanted_index(contact.title, wanted_titles),
            _level_index(seniority_of(contact.title)),
            contact.rank,
        )

    ordered = sorted(contacts, key=key)
    return [
        RankedContact(contact, position, seniority_of(contact.title))
        for position, contact in enumerate(ordered, start=1)
    ]
