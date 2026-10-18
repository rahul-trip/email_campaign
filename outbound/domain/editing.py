"""How far an operator's edit moved an email from what the engine wrote."""

from __future__ import annotations

from difflib import SequenceMatcher


def edit_distance(generated: str, final: str) -> float:
    """0.0 for an unchanged email, up to 1.0 for a complete rewrite. Whitespace is ignored."""
    a, b = " ".join(generated.split()), " ".join(final.split())
    if a == b:
        return 0.0
    return round(1.0 - SequenceMatcher(None, a, b, autojunk=False).ratio(), 4)
