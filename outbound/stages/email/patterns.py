"""Company email patterns such as ``first.last``, learned once and applied to colleagues.

Only one address is ever built from a learned pattern. Guessing several permutations and
verifying each would burn verifier credits and risk bounces, which the plan forbids.
"""

from __future__ import annotations

import re
import unicodedata

PATTERNS = (
    "{first}.{last}",
    "{first}",
    "{f}{last}",
    "{first}{last}",
    "{f}.{last}",
    "{last}",
    "{first}_{last}",
    "{first}{l}",
    "{last}.{first}",
)


def _ascii(name: str) -> str:
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z]", "", folded.lower())


def _parts(first: str, last: str) -> dict[str, str]:
    f, l_ = _ascii(first), _ascii(last)
    return {"first": f, "last": l_, "f": f[:1], "l": l_[:1]}


def local_part(pattern: str, first: str, last: str) -> str | None:
    """The mailbox name a pattern gives for a person, or None if a needed name is missing."""
    parts = _parts(first, last)
    needed = set(re.findall(r"\{(\w+)\}", pattern))
    if not needed or any(not parts[name] for name in needed):
        return None
    return pattern.format(**parts)


def build_address(pattern: str, first: str, last: str, domain: str) -> str | None:
    local = local_part(pattern, first, last)
    return f"{local}@{domain}" if local else None


def infer_pattern(email: str, first: str, last: str) -> str | None:
    """Which known pattern produces this address for this person, if any."""
    local, _, _domain = email.lower().partition("@")
    for pattern in PATTERNS:
        if local_part(pattern, first, last) == local:
            return pattern
    return None


def matches_person(email: str, first: str, last: str) -> bool:
    """Whether a published address plausibly belongs to this person (their surname in it)."""
    local = email.lower().partition("@")[0]
    surname = _ascii(last)
    return len(surname) >= 3 and surname in re.sub(r"[^a-z]", "", local)
