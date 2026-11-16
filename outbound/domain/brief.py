"""The ideal-customer brief: who a campaign looks for, in parts the engine can use.

A model drafts it from the campaign's description and the sender profile; the operator can edit
it. Discovery picks its sources and searches from it, screening keeps or drops each company
found against it, and research qualifies a lead criterion by criterion. Stored as JSON on the
campaign (``campaigns.icp_brief``). Parsing is tolerant: what a model or a person wrote is
cleaned rather than refused, so a bad field never stops a run.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from enum import StrEnum
from typing import Any

MAX_ITEMS = 12
MAX_ITEM_CHARS = 120
MAX_SUMMARY_CHARS = 1_000
MAX_WEIGHT = 3
_SIC = re.compile(r"^\d{4,5}$")  # a UK SIC code


class CompanyType(StrEnum):
    STARTUP = "startup"
    SME = "sme"
    ENTERPRISE = "enterprise"
    PUBLIC_SECTOR = "public_sector"
    ANY = "any"


@dataclass(frozen=True)
class Criterion:
    """A must-have, with how much it counts (1 to 3)."""

    text: str
    weight: int = 1


@dataclass(frozen=True)
class Brief:
    summary: str = ""
    company_type: CompanyType = CompanyType.ANY
    keywords: tuple[str, ...] = ()
    segments: tuple[str, ...] = ()
    regions: tuple[str, ...] = ()
    size_range: str = ""
    founded_after: int | None = None
    funding_stages: tuple[str, ...] = ()
    industry_codes: tuple[str, ...] = ()  # UK SIC codes, for the Companies House search
    must_haves: tuple[Criterion, ...] = ()
    disqualifiers: tuple[str, ...] = ()
    buying_signals: tuple[str, ...] = ()
    source_hints: tuple[str, ...] = ()  # kinds of page that list such companies
    seed_companies: tuple[str, ...] = ()  # examples of an ideal customer, for lookalikes

    @property
    def is_empty(self) -> bool:
        return self == Brief()

    @classmethod
    def from_json(cls, data: object) -> Brief:
        if not isinstance(data, Mapping):
            return cls()
        try:
            kind = CompanyType(str(data.get("company_type") or "any").strip().lower())
        except ValueError:
            kind = CompanyType.ANY
        founded = data.get("founded_after")
        return cls(
            summary=_text(data.get("summary"), MAX_SUMMARY_CHARS),
            company_type=kind,
            keywords=_texts(data.get("keywords")),
            segments=_texts(data.get("segments")),
            regions=_texts(data.get("regions")),
            size_range=_text(data.get("size_range"), MAX_ITEM_CHARS),
            founded_after=(
                founded if isinstance(founded, int) and 1900 <= founded <= 2100 else None
            ),
            funding_stages=_texts(data.get("funding_stages")),
            industry_codes=tuple(c for c in _texts(data.get("industry_codes")) if _SIC.match(c)),
            must_haves=_criteria(data.get("must_haves")),
            disqualifiers=_texts(data.get("disqualifiers")),
            buying_signals=_texts(data.get("buying_signals")),
            source_hints=_texts(data.get("source_hints")),
            seed_companies=_texts(data.get("seed_companies")),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "company_type": self.company_type.value,
            "keywords": list(self.keywords),
            "segments": list(self.segments),
            "regions": list(self.regions),
            "size_range": self.size_range,
            "founded_after": self.founded_after,
            "funding_stages": list(self.funding_stages),
            "industry_codes": list(self.industry_codes),
            "must_haves": [{"text": c.text, "weight": c.weight} for c in self.must_haves],
            "disqualifiers": list(self.disqualifiers),
            "buying_signals": list(self.buying_signals),
            "source_hints": list(self.source_hints),
            "seed_companies": list(self.seed_companies),
        }


def gaps(brief: Brief) -> tuple[str, ...]:
    """What is missing from a brief that makes discovery and scoring weaker, in plain words
    for the person editing it. Empty when it is well specified."""
    out: list[str] = []
    if not brief.summary:
        out.append(
            "Say in a sentence who you look for: the summary is what a company is judged against."
        )
    if not brief.must_haves:
        out.append(
            "No must-haves: a company is judged only against the summary"
            + (", the company type and the size." if brief.summary else ".")
            + " Add two or three facts a good customer must have."
        )
    if not brief.disqualifiers:
        out.append(
            "No rule-outs: vendors, competitors and companies that are too big will not be"
            " turned away. Say who you do not want."
        )
    if not brief.keywords:
        out.append(
            "No keywords: directories are searched by the words of the summary and segments."
        )
    return tuple(out)


def lacks_substance(brief: Brief) -> bool:
    """No keywords and no must-haves: discovery has nothing to search by and scoring nothing
    to judge by, as when a model's drafting failed and a plain fallback was stored."""
    return not brief.keywords and not brief.must_haves


def fill_gaps(brief: Brief, drafted: Brief) -> Brief:
    """``brief`` with every field it leaves empty taken from ``drafted``. What a person
    wrote is never replaced."""
    changes: dict[str, Any] = {}
    empty = Brief()
    for field in fields(Brief):
        if getattr(brief, field.name) == getattr(empty, field.name):
            changes[field.name] = getattr(drafted, field.name)
    return replace(brief, **changes)


def _text(value: object, limit: int) -> str:
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


def _texts(value: object) -> tuple[str, ...]:
    """Strings only, trimmed and shortened, blanks and repeats (ignoring case) dropped."""
    if not isinstance(value, list | tuple):
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _text(item, MAX_ITEM_CHARS)
        if text and text.lower() not in seen:
            seen.add(text.lower())
            out.append(text)
    return tuple(out[:MAX_ITEMS])


def _criteria(value: object) -> tuple[Criterion, ...]:
    if not isinstance(value, list | tuple):
        return ()
    out: list[Criterion] = []
    for item in value:
        raw = item.get("text") if isinstance(item, Mapping) else item
        text = _text(raw, MAX_ITEM_CHARS)
        if not text:
            continue
        weight = item.get("weight") if isinstance(item, Mapping) else 1
        weight = weight if isinstance(weight, int) and not isinstance(weight, bool) else 1
        out.append(Criterion(text, min(max(weight, 1), MAX_WEIGHT)))
    return tuple(out[:MAX_ITEMS])
