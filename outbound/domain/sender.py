"""Who an email comes from (Phase 6c): the company in the workspace profile, the person in the
mailbox it is sent from.

The workspace profile holds the legal identity printed in footers and what the writer may say
about the company. A mailbox's ``sender`` holds the person signing from it: name, title,
greeting and style examples. Where the mailbox says something, it wins; otherwise the
profile's value stands, so a workspace with one mailbox and a full profile changes nothing.
"""

from __future__ import annotations

from typing import Any

PERSON_FIELDS = ("signature_name", "signature_title", "greeting", "style_examples")


def _given(value: Any) -> bool:
    if isinstance(value, list | tuple):
        return any(str(item).strip() for item in value)
    return bool(str(value or "").strip())


def sender_for(profile: dict[str, Any], mailbox_sender: dict[str, Any] | None) -> dict[str, Any]:
    """The profile with the mailbox's person-level fields laid over it."""
    merged = dict(profile)
    for field in PERSON_FIELDS:
        value = (mailbox_sender or {}).get(field)
        if _given(value):
            merged[field] = value
    return merged


def person_of(sender: dict[str, Any] | None) -> dict[str, Any]:
    """Only the person-level fields, as a mailbox stores them."""
    return {f: sender[f] for f in PERSON_FIELDS if sender and _given(sender.get(f))}
