"""Who counts as operator input (rule 7): people and the integrations they set up, never the
engine or a vendor."""

from __future__ import annotations

from outbound.domain.actors import INTEGRATION_WEBHOOK, OPERATOR, SYSTEM, is_operator, provider


def test_people_and_their_integrations_are_operator_input() -> None:
    assert is_operator(OPERATOR)
    assert is_operator("user:01a1")
    assert is_operator(INTEGRATION_WEBHOOK)


def test_the_engine_and_vendors_are_not() -> None:
    assert not is_operator(SYSTEM)
    assert not is_operator(provider("hunter"))
    assert not is_operator("users:x")
