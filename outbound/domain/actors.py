"""Who made a change. Operator input outranks anything the engine writes."""

from __future__ import annotations

OPERATOR = "operator"
SYSTEM = "system"
INTEGRATION_WEBHOOK = "integration:webhook"  # the signed intake webhook, on the operator's behalf


def provider(name: str) -> str:
    return f"provider:{name}"


def is_operator(actor: str) -> bool:
    """People and the integrations they set up: ``operator`` (the CLI), ``user:<id>`` (a signed-in
    person, Phase 6b) or ``integration:<name>`` (the intake webhook)."""
    return actor == OPERATOR or actor.startswith(("user:", "integration:"))
