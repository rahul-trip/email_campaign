"""Country names an operator might type, reduced to an ISO 3166-1 alpha-2 code."""

from __future__ import annotations

import re

_NAMES = {
    "uk": "GB", "united kingdom": "GB", "great britain": "GB", "britain": "GB", "england": "GB",
    "scotland": "GB", "wales": "GB", "northern ireland": "GB",
    "us": "US", "usa": "US", "united states": "US", "united states of america": "US",
    "america": "US",
    "germany": "DE", "deutschland": "DE", "austria": "AT", "france": "FR", "netherlands": "NL",
    "holland": "NL", "the netherlands": "NL", "ireland": "IE", "sweden": "SE", "canada": "CA",
    "india": "IN", "spain": "ES", "italy": "IT", "denmark": "DK", "norway": "NO",
    "finland": "FI", "belgium": "BE", "switzerland": "CH", "poland": "PL", "portugal": "PT",
    "australia": "AU", "new zealand": "NZ", "singapore": "SG", "uae": "AE",
    "united arab emirates": "AE",
}  # fmt: skip


def country_code(value: str | None) -> str | None:
    """``"United Kingdom"``, ``"uk"`` and ``"GB"`` become ``"GB"``; anything unclear is None."""
    if not value:
        return None
    text = re.sub(r"\s+", " ", value.strip().lower())
    if text in _NAMES:
        return _NAMES[text]
    if len(text) == 2 and text.isalpha():
        return text.upper()
    return None
