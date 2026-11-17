"""Checking a LinkedIn connection note and follow-up message. Pure; no I/O.

The operator pastes these into LinkedIn by hand, so the limits are LinkedIn's and the voice is a
person's: a free account's connection note is 200 characters at most, and a message that reads
as a template, a link or an email's wording gets ignored.
"""

from __future__ import annotations

import re

from outbound.domain.copy_lint import BANNED_PHRASES, count_words

NOTE_MAX_CHARS = 200  # what a free LinkedIn account allows with a connection request
MESSAGE_WORDS = (60, 100)

_LINK = re.compile(r"https?://|www\.|\b[a-z0-9-]+\.(?:com|io|co|net|org|ai|uk|de)\b", re.IGNORECASE)
_PLACEHOLDER = re.compile(r"\[[^\]]+\]|\{\{|\}\}|<[A-Za-z ]+>")
_EMAIL_WORDS = ("this email", "my email", "unsubscribe", "subject:")
_ADDRESS = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def lint_linkedin(note: str, message: str) -> list[str]:
    """What is wrong with the pair, in words a writer can act on; empty when it passes."""
    issues: list[str] = []
    if not note.strip():
        issues.append("the connection note is empty")
    elif len(note.strip()) > NOTE_MAX_CHARS:
        issues.append(
            f"the connection note is {len(note.strip())} characters; LinkedIn allows"
            f" {NOTE_MAX_CHARS}: cut it"
        )
    low, high = MESSAGE_WORDS
    words = count_words(message)
    if words < low or words > high:
        issues.append(f"the message is {words} words; write {low} to {high}")
    for label, text in (("note", note), ("message", message)):
        lowered = text.lower()
        if _LINK.search(text) or _ADDRESS.search(text):
            issues.append(f"the {label} has a link or an address: leave it out")
        if _PLACEHOLDER.search(text):
            issues.append(f"the {label} has a placeholder left in it")
        found = [p for p in (*BANNED_PHRASES, *_EMAIL_WORDS) if p in lowered]
        if found:
            issues.append(f"the {label} uses wording that reads as a template: {found[0].strip()}")
    return issues
