"""Deterministic checks on a draft email: rules first, taste second.

Length, reading level, questions and style are measured on the paragraphs the writer produced
(``core``). Greeting, sign-off and footer are added by code, so the writer cannot shorten or
change them. A report with any issue is "flagged": the copy stage still hands the draft to the
operator, but with the reasons attached.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Phrases that mark a message as written by a model (or by a mass mailer). Matched anywhere,
# lower case, so "synerg" catches synergy and synergies, "seamless" catches seamlessly.
BANNED_PHRASES = (
    "i hope this email finds you well",
    "i hope this finds you well",
    "hope you're well",
    "hope you are well",
    "in today's fast-paced",
    "ever-evolving",
    "at the forefront",
    "in the realm of",
    "revolutionary",
    "delighted to connect",
    "synerg",
    "leverage",
    "cutting-edge",
    "game-changer",
    "game changer",
    "i wanted to reach out",
    "i'm reaching out",
    "i am reaching out",
    "reaching out",
    "touch base",
    "circle back",
    "pick your brain",
    "just checking in",
    "i came across",
    "caught my eye",
    "i noticed",
    "we believe",
    "strong potential",
    "seamless",
    "empower",
    "enhanced intelligence",
    "excellent track record",
    "we admire",
    "greatly admire",
    "impressive",
    "delve",
    "unlock",
    "robust",
    "streamline",
    "partnership opportunit",
    "tapestry",
)


@dataclass(frozen=True)
class LintRules:
    first_touch_words: tuple[int, int] = (120, 200)
    follow_up_words: tuple[int, int] = (25, 50)
    subject_words: tuple[int, int] = (2, 6)
    max_reading_grade: float = 10.0
    questions: tuple[int, int] = (1, 2)
    max_dashes: int = 1  # em dashes; a person uses one now and then, a model uses many
    banned_phrases: tuple[str, ...] = BANNED_PHRASES

    @classmethod
    def with_length(cls, low: int, high: int) -> LintRules:
        """The default rules with the workspace's first-email length."""
        return cls(first_touch_words=(low, high))


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


_BULLET = re.compile(r"^\s*(?:[•\u2022\-*\u2013]|\d+[.)])\s+\S", re.MULTILINE)
_EMAIL_ADDRESS = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"https?://|www\.|\b[a-z0-9-]+\.(?:com|io|co|net|org|ai|uk|de)/", re.IGNORECASE)
_WORDS = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\u2019-]*")


def count_words(text: str) -> int:
    return len(_WORDS.findall(text))


_VOWEL_GROUP = re.compile(r"[aeiouy]+")
_SENTENCE_END = re.compile(r"[.!?]+(?:\s|$)")


def _syllables(word: str) -> int:
    """A count by vowel groups, with a silent final "e" dropped. Needs no word list."""
    word = re.sub(r"[^a-z]", "", word.lower())
    count = len(_VOWEL_GROUP.findall(word))
    if word.endswith("e") and not word.endswith(("le", "ee", "ye")) and count > 1:
        count -= 1
    return max(count, 1) if word else 0


def reading_grade(text: str) -> float:
    """Flesch-Kincaid grade level: 0.39 * words/sentence + 11.8 * syllables/word - 15.59."""
    words = _WORDS.findall(text)
    if not words:
        return 0.0
    sentences = max(len(_SENTENCE_END.findall(text.strip())), 1)
    syllables = sum(_syllables(w) for w in words)
    return 0.39 * len(words) / sentences + 11.8 * syllables / len(words) - 15.59


def lint(
    *,
    body: str,
    subject: str,
    step: int,
    footer: str | None = None,
    core: str | None = None,
    rules: LintRules = LintRules(),  # noqa: B008 - frozen, so safe to share
) -> LintReport:
    """``body`` is the whole email as it will be saved, footer included.

    ``core`` is just the paragraphs the writer produced. When given, length and style are
    measured on it; otherwise on ``body`` without the footer.
    """
    main = (
        core.strip()
        if core is not None
        else (body.replace(footer, "").strip() if footer else body.strip())
    )
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

    grade = reading_grade(main) if main else 0.0
    if grade > rules.max_reading_grade:
        issues.append(
            LintIssue(
                "reading_level",
                f"Reading grade is {grade:.1f}; it must be {rules.max_reading_grade} or lower. "
                "Use shorter sentences and plainer words.",
            )
        )

    questions = main.count("?")
    low_q, high_q = rules.questions
    if not low_q <= questions <= high_q:
        issues.append(
            LintIssue(
                "call_to_action",
                f"The email has {questions} question marks; it needs {low_q} to {high_q}, with"
                " a clear ask at the end.",
            )
        )

    if _BULLET.search(main):
        issues.append(
            LintIssue("bullets", "Write paragraphs, not a list: remove every bullet or number.")
        )

    if main.count("\u2014") > rules.max_dashes:
        issues.append(
            LintIssue(
                "dashes",
                f"Use at most {rules.max_dashes} em dash; use full stops and commas instead.",
            )
        )

    if step == 0 and _URL.search(main):
        issues.append(LintIssue("links", "The first email must not contain a link."))

    if _EMAIL_ADDRESS.search(main):
        issues.append(
            LintIssue("address_in_body", "Remove the email address; the body must not contain one.")
        )

    lowered = main.lower()
    for phrase in rules.banned_phrases:
        if phrase in lowered:
            issues.append(LintIssue("banned_phrase", f"Remove the phrase {phrase!r}."))

    if footer and footer not in body:
        issues.append(LintIssue("footer", "The required country footer is missing."))

    return LintReport(tuple(issues), words, grade)
