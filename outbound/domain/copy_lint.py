"""Deterministic checks on a draft email: rules first, taste second.

Word counts include the greeting and sign-off but exclude the footer, which is legal text the
writer cannot shorten. A report with any issue is "flagged": the copy stage still hands the
draft to the operator, but with the reasons attached.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import textstat

BANNED_PHRASES = (
    "i hope this email finds you well",
    "i hope this finds you well",
    "hope you're well",
    "in today's fast-paced",
    "revolutionary",
    "delighted to connect",
    "synergy",
    "leverage",
    "cutting-edge",
    "game-changer",
    "i wanted to reach out",
    "reaching out",
    "touch base",
    "circle back",
    "pick your brain",
    "just checking in",
)


@dataclass(frozen=True)
class LintRules:
    first_touch_words: tuple[int, int] = (50, 85)
    follow_up_words: tuple[int, int] = (25, 50)
    subject_words: tuple[int, int] = (2, 5)
    max_reading_grade: float = 6.5
    banned_phrases: tuple[str, ...] = BANNED_PHRASES


@dataclass(frozen=True)
class LintIssue:
    rule: str
    message: str


@dataclass(frozen=True)
class LintReport:
    issues: tuple[LintIssue, ...] = field(default=())
    word_count: int = 0
    reading_grade: float = 0.0

    @property
    def flagged(self) -> bool:
        return bool(self.issues)

    def to_json(self) -> dict[str, Any]:
        return {
            "flagged": self.flagged,
            "word_count": self.word_count,
            "reading_grade": round(self.reading_grade, 1),
            "issues": [{"rule": i.rule, "message": i.message} for i in self.issues],
        }

    def feedback(self) -> str:
        """The issues as instructions for a rewrite."""
        return "\n".join(f"- {issue.message}" for issue in self.issues)


_URL = re.compile(r"https?://|www\.|\b[a-z0-9-]+\.(?:com|io|co|net|org|ai|uk|de)/", re.IGNORECASE)
_WORDS = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\u2019-]*")


def count_words(text: str) -> int:
    return len(_WORDS.findall(text))


def lint(
    *,
    body: str,
    subject: str,
    step: int,
    footer: str | None = None,
    rules: LintRules = LintRules(),  # noqa: B008 - frozen, so safe to share
) -> LintReport:
    """``body`` is the whole email as it will be saved, footer included."""
    main = body.replace(footer, "").strip() if footer else body.strip()
    issues: list[LintIssue] = []

    low, high = rules.first_touch_words if step == 0 else rules.follow_up_words
    words = count_words(main)
    if not low <= words <= high:
        issues.append(
            LintIssue("length", f"The email is {words} words; it must be {low} to {high} words.")
        )

    subject_words = count_words(subject)
    low_s, high_s = rules.subject_words
    if not low_s <= subject_words <= high_s or subject != subject.lower():
        issues.append(
            LintIssue(
                "subject",
                f"The subject must be {low_s} to {high_s} words, all lower case (got {subject!r}).",
            )
        )

    grade = float(textstat.flesch_kincaid_grade(main)) if main else 0.0
    if grade > rules.max_reading_grade:
        issues.append(
            LintIssue(
                "reading_level",
                f"Reading grade is {grade:.1f}; it must be {rules.max_reading_grade} or lower. "
                "Use shorter sentences and plainer words.",
            )
        )

    questions = main.count("?")
    if questions != 1:
        issues.append(
            LintIssue(
                "call_to_action",
                f"The email has {questions} questions; it needs exactly one, as the closing ask.",
            )
        )

    if step == 0 and _URL.search(main):
        issues.append(LintIssue("links", "The first email must not contain a link."))

    lowered = main.lower()
    for phrase in rules.banned_phrases:
        if phrase in lowered:
            issues.append(LintIssue("banned_phrase", f"Remove the phrase {phrase!r}."))

    if footer and footer not in body:
        issues.append(LintIssue("footer", "The required country footer is missing."))

    return LintReport(tuple(issues), words, grade)
