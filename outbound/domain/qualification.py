"""Qualifying a researched company against the campaign's brief, criterion by criterion (no I/O).

The brief's must-haves, buying signals and disqualifiers become numbered checks (``checks``:
``M1``, ``S1``, ``D1``...) that a model answers one by one with a verdict, its evidence and where
it found it. ``qualify`` turns those answers into the fit score and a reason a person can check:

- a disqualifier that is met rules the company out (score 0), whatever else is true;
- must-haves give up to 80, counted by weight, an unknown one counting half (60 when none is
  set, so a brief of rule-outs only passes the default fit minimum of 60 when none is met);
- each buying signal that is met adds 10, up to 20.

The scale meets the gate's default minimum of 60: every must-have met passes, and a company
nothing is known about fails.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from outbound.domain.brief import Brief

MUST_HAVE_POINTS = 80
NO_MUST_HAVES = 60
SIGNAL_POINTS = 10
MAX_SIGNAL_POINTS = 20
MAX_TEXT = 300


class Verdict(StrEnum):
    MET = "met"
    NOT_MET = "not_met"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Check:
    """One criterion the model answers by its id."""

    id: str
    kind: str  # "must_have", "signal" or "disqualifier"
    text: str
    weight: int


@dataclass(frozen=True)
class Assessed:
    """A check with the model's answer to it."""

    check: Check
    verdict: Verdict
    evidence: str = ""
    source: str = ""


@dataclass(frozen=True)
class Qualification:
    score: int
    reason: str
    ruled_out: bool
    items: tuple[Assessed, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "reason": self.reason,
            "ruled_out": self.ruled_out,
            "criteria": [
                {
                    "id": i.check.id,
                    "kind": i.check.kind,
                    "criterion": i.check.text,
                    "weight": i.check.weight,
                    "verdict": i.verdict.value,
                    "evidence": i.evidence,
                    "source": i.source,
                }
                for i in self.items
            ],
        }


def checks(brief: Brief) -> list[Check]:
    """The brief's criteria, numbered: must-haves, then signals, then disqualifiers."""
    return [
        *(Check(f"M{n}", "must_have", c.text, c.weight) for n, c in enumerate(brief.must_haves, 1)),
        *(Check(f"S{n}", "signal", t, 1) for n, t in enumerate(brief.buying_signals, 1)),
        *(Check(f"D{n}", "disqualifier", t, 1) for n, t in enumerate(brief.disqualifiers, 1)),
    ]


def _text(value: object) -> str:
    return " ".join(str(value).split())[:MAX_TEXT] if isinstance(value, str) else ""


def _assess(check: Check, answer: object) -> Assessed:
    if not isinstance(answer, Mapping):
        return Assessed(check, Verdict.UNKNOWN)
    raw = answer.get("verdict")
    verdict = Verdict(raw) if raw in set(Verdict) else Verdict.UNKNOWN
    return Assessed(check, verdict, _text(answer.get("evidence")), _text(answer.get("source")))


def qualify(brief: Brief, answers: Mapping[str, object]) -> Qualification:
    """The fit score and reason from the model's answer to each check; a check it did not
    answer, or answered with nonsense, is unknown."""
    items = tuple(_assess(c, answers.get(c.id)) for c in checks(brief))
    for item in items:
        if item.check.kind == "disqualifier" and item.verdict is Verdict.MET:
            why = f" ({item.evidence})" if item.evidence else ""
            return Qualification(0, f"Ruled out: {item.check.text}{why}", True, items)

    musts = [i for i in items if i.check.kind == "must_have"]
    signals = [i.check.text for i in items if i.check.kind == "signal" and i.verdict is Verdict.MET]
    total = sum(i.check.weight for i in musts)
    if total:
        met = sum(i.check.weight for i in musts if i.verdict is Verdict.MET)
        unknown = sum(i.check.weight for i in musts if i.verdict is Verdict.UNKNOWN)
        base = int(MUST_HAVE_POINTS * (met + unknown / 2) / total + 0.5)
    else:
        base = NO_MUST_HAVES
    score = min(100, base + min(MAX_SIGNAL_POINTS, SIGNAL_POINTS * len(signals)))

    parts: list[str] = []
    if musts:
        count = sum(1 for i in musts if i.verdict is Verdict.MET)
        parts.append(f"Meets {count} of {len(musts)} must-haves")
        missing = [i.check.text for i in musts if i.verdict is Verdict.NOT_MET]
        unknowns = [i.check.text for i in musts if i.verdict is Verdict.UNKNOWN]
        if missing:
            parts.append("missing: " + ", ".join(missing))
        if unknowns:
            parts.append("not known: " + ", ".join(unknowns))
    else:
        parts.append("No must-haves set")
    if signals:
        parts.append("signs they may buy now: " + ", ".join(signals))
    return Qualification(score, "; ".join(parts), False, items)
