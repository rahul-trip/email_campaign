"""Workspace slugs: the short, URL-safe name a workspace is reached by (``/w/<slug>``)."""

from __future__ import annotations

import re
import unicodedata

MAX_LENGTH = 48
_NOT_ALLOWED = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """``"Acme Énergie Ltd."`` → ``"acme-energie-ltd"``; never empty."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = _NOT_ALLOWED.sub("-", plain.lower()).strip("-")[:MAX_LENGTH].rstrip("-")
    return slug or "workspace"


def unique_slug(name: str, taken: set[str]) -> str:
    """The name's slug, with ``-2``, ``-3``… added until it is not in ``taken``."""
    base = slugify(name)
    if base not in taken:
        return base
    number = 2
    while True:
        suffix = f"-{number}"
        candidate = base[: MAX_LENGTH - len(suffix)].rstrip("-") + suffix
        if candidate not in taken:
            return candidate
        number += 1
