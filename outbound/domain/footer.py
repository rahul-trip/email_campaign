"""The country footer: legal text built from the policy template and the sender's own details."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from outbound.domain.enums import Provenance

_PLACEHOLDER = re.compile(r"\{(\w+)\}")

# Where we say the address came from, in words a recipient would recognise.
DATA_SOURCE = {
    Provenance.OPERATOR_GIVEN: "a personal introduction",
    Provenance.PUBLICLY_PUBLISHED: "your company's website",
    Provenance.API_DATABASE: "a professional business directory",
    Provenance.PATTERN_INFERRED: "your company's public email format",
    Provenance.REFERRAL: "a referral",
}

# Template placeholder -> the key in the workspace's sender profile.
_SENDER_KEYS = {
    "sender_legal_name": "legal_name",
    "postal_address": "postal_address",
    "registration_details": "registration_details",
    "contact_info": "contact_info",
}


class MissingProfileField(ValueError):
    def __init__(self, fields: list[str]) -> None:
        super().__init__(f"the sender profile needs: {', '.join(fields)}")
        self.fields = fields


def render_footer(template: str, sender: Mapping[str, Any], provenance: Provenance | None) -> str:
    """Fill ``template``. A blank sender field is an error: a footer with a hole is not legal."""
    missing: list[str] = []
    values: dict[str, str] = {}
    for name in dict.fromkeys(_PLACEHOLDER.findall(template)):
        if name == "data_source":
            values[name] = DATA_SOURCE.get(provenance or Provenance.API_DATABASE, "a public source")
            continue
        key = _SENDER_KEYS.get(name, name)
        value = str(sender.get(key) or "").strip()
        if not value:
            missing.append(key)
        values[name] = value
    if missing:
        raise MissingProfileField(missing)
    return _PLACEHOLDER.sub(lambda m: values[m.group(1)], template)
