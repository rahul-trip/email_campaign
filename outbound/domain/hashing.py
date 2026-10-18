"""Hashes for the suppression list: the address itself is never stored."""

from __future__ import annotations

import hashlib


def normalise(value: str) -> str:
    return value.strip().lower()


def hash_value(value: str) -> str:
    """sha256 of the lower-cased, trimmed value."""
    return hashlib.sha256(normalise(value).encode("utf-8")).hexdigest()
