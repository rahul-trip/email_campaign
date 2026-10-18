"""Who made a change. Operator input outranks anything the engine writes."""

from __future__ import annotations

OPERATOR = "operator"
SYSTEM = "system"


def provider(name: str) -> str:
    return f"provider:{name}"


def is_operator(actor: str) -> bool:
    """Operators are ``operator`` (single-user mode) or ``user:<id>`` (Phase 6)."""
    return actor == OPERATOR or actor.startswith("user:")
