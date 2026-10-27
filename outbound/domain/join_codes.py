"""The short code a team shares so a signed-in person can ask to join its workspace."""

from __future__ import annotations

import secrets

# No 0/O or 1/I/L: a code is read aloud and typed by hand.
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
LENGTH = 8


def new_join_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))


def normalise_join_code(text: str) -> str:
    """What was typed, as stored: upper case, without spaces or dashes."""
    return "".join(ch for ch in text.upper() if ch.isalnum())
