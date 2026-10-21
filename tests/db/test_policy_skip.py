"""Skipping the country rule: for one lead from a stage on, or for the whole workspace."""

from __future__ import annotations

from typing import Any

import pytest

from outbound.db.errors import NotFound
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.entities import Company, CountryPolicy
from outbound.domain.enums import (
    CompanySource,
    CompanyStatus,
    EntityType,
    HoldReason,
    LegalEntityType,
    PolicyRule,
    PolicyStage,
    SuppressionKind,
    SuppressionReason,
)
from outbound.domain.errors import InvalidInput
from outbound.domain.policies import PolicyOutcome, policy_skipped_at
from outbound.runner.guards import Guards
from outbound.runner.runner import Runner
from outbound.services.leads import LeadError, LeadService
from outbound.services.settings import SettingsService
from outbound.stages.gate import GateStage
from outbound.stages.policy import policy_decision_for
from tests.db.test_runner import FakeStage

C = CompanyStatus


def lead(
    factory: UnitOfWorkFactory,
    ws: str,
    *,
    country: str = "DE",
    rule: PolicyRule = PolicyRule.BLOCK,
    path: tuple[CompanyStatus, ...] = (C.RESEARCHED,),
) -> Company:
    with factory(ws) as uow:
        uow.policies.upsert(CountryPolicy(country, rule))
        company = uow.companies.create(
            domain=f"acme.{country.lower()}", source=CompanySource.MANUAL, country_code=country
        )
        company = uow.companies.update_fields(
            company.id,
            {"legal_entity_type": LegalEntityType.CORPORATE_SUBSCRIBER},
            actor="system",
            expected_version=company.row_version,
        )
        version = company.row_version
        for step in path:
            company = uow.companies.transition(company.id, step, expected_version=version)
            version = company.row_version
        uow.commit()
        return company


def run(factory: UnitOfWorkFactory, ws: str, *stages: Any) -> None:
    Runner(factory, ws, list(stages), Guards()).run_pipeline()


def get(factory: UnitOfWorkFactory, ws: str, company_id: str) -> Company:
    with factory(ws) as uow:
        return uow.companies.get(company_id)


def switch(factory: UnitOfWorkFactory, ws: str, **changes: Any) -> None:
    SettingsService(factory, ws).update_workspace_settings(changes)


def leads(factory: UnitOfWorkFactory, ws: str) -> LeadService:
    return LeadService(factory, ws)


@pytest.mark.parametrize(
    ("stage", "skip_from", "skipped"),
    [
        ("gate", None, False),
        ("gate", PolicyStage.GATE, True),
        ("deliver", PolicyStage.GATE, True),
        ("gate", PolicyStage.EMAIL, False),
        ("contacts", PolicyStage.EMAIL, False),
        ("email", PolicyStage.EMAIL, True),
        ("copy", PolicyStage.EMAIL, True),
        (None, PolicyStage.COPY, True),  # releasing a hold: any skip counts
        ("research", PolicyStage.GATE, False),  # not a stage that checks the rule
    ],
)
def test_a_skip_applies_from_its_stage_onward(
    stage: str | None, skip_from: PolicyStage | None, skipped: bool
) -> None:
    assert policy_skipped_at(stage, skip_from) is skipped


def test_with_country_rules_switched_off_a_blocked_country_is_qualified(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    company = lead(factory, ws)
    switch(factory, ws, country_policy_enabled=False)
    run(factory, ws, GateStage())
    after = get(factory, ws, company.id)
    assert after.status is C.QUALIFIED
    assert after.policy_decision is not None
    assert after.policy_decision["skipped"] is True
    assert "switched off" in after.policy_decision["reasons"][0]


def test_suppression_still_wins_when_the_rules_are_off(factory: UnitOfWorkFactory, ws: str) -> None:
    company = lead(factory, ws, path=(C.RESEARCHED, C.QUALIFIED))
    switch(factory, ws, country_policy_enabled=False)
    with factory(ws) as uow:
        uow.suppressions.add(SuppressionKind.DOMAIN, company.domain, SuppressionReason.OPT_OUT)
        uow.commit()
    stage = FakeStage("contacts", C.QUALIFIED, C.CONTACTS_FOUND, guard_policy=True)
    run(factory, ws, stage)
    assert stage.seen == []
    assert get(factory, ws, company.id).status is C.SUPPRESSED


def test_a_lead_blocked_at_the_gate_goes_on_once_the_rule_is_skipped_from_there(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    company = lead(factory, ws)
    run(factory, ws, GateStage())
    assert get(factory, ws, company.id).status is C.DISQUALIFIED
    service = leads(factory, ws)
    with pytest.raises(InvalidInput, match="say why"):
        service.skip_policy(company.id, PolicyStage.GATE, "  ")
    moved = service.skip_policy(company.id, PolicyStage.GATE, "they asked us to write")
    assert (moved.status, moved.policy_skip_from) == (C.QUALIFIED, PolicyStage.GATE)
    with factory(ws) as uow:
        events = uow.events.for_entities([(EntityType.COMPANY, company.id)])
    granted = [e for e in events if e.type == "policy_skip_granted"]
    assert [(e.actor, e.data) for e in granted] == [
        ("operator", {"from_stage": "gate", "reason": "they asked us to write"})
    ]


def test_a_hold_at_a_later_stage_resumes_there_and_a_later_start_is_refused(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    company = lead(factory, ws, rule=PolicyRule.CONSENT_REQUIRED, path=(C.RESEARCHED, C.QUALIFIED))
    run(factory, ws, FakeStage("contacts", C.QUALIFIED, C.CONTACTS_FOUND, guard_policy=True))
    held = get(factory, ws, company.id)
    assert (held.status, held.hold_reason) == (C.HELD, HoldReason.CONSENT_REQUIRED)
    service = leads(factory, ws)
    assert service.detail(company.id).held_at is PolicyStage.CONTACTS
    with pytest.raises(LeadError, match="contacts step"):
        service.skip_policy(company.id, PolicyStage.EMAIL, "too late")
    moved = service.skip_policy(company.id, PolicyStage.CONTACTS, "known contact")
    assert moved.status is C.QUALIFIED
    stage = FakeStage("contacts", C.QUALIFIED, C.CONTACTS_FOUND, guard_policy=True)
    run(factory, ws, stage)
    assert get(factory, ws, company.id).status is C.CONTACTS_FOUND


def test_a_skip_can_be_revoked_until_the_email_is_approved(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    company = lead(factory, ws, path=(C.RESEARCHED, C.QUALIFIED))
    service = leads(factory, ws)
    service.skip_policy(company.id, PolicyStage.CONTACTS, "known contact")
    assert service.revoke_policy_skip(company.id).policy_skip_from is None
    with pytest.raises(LeadError, match="not skipped"):
        service.revoke_policy_skip(company.id)
    approved = lead(
        factory,
        ws,
        country="AT",
        path=(C.RESEARCHED, C.QUALIFIED, C.CONTACTS_FOUND, C.EMAIL_READY, C.COPY_READY),
    )
    service.skip_policy(approved.id, PolicyStage.GATE, "known contact")
    with factory(ws) as uow:
        current = uow.companies.get(approved.id)
        uow.companies.transition(approved.id, C.APPROVED, expected_version=current.row_version)
        uow.commit()
    with pytest.raises(LeadError, match="Reject it first"):
        service.revoke_policy_skip(approved.id)


def test_turning_the_rules_off_then_releasing_lets_held_leads_go_on_and_back_on_holds_again(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    company = lead(factory, ws, rule=PolicyRule.CONSENT_REQUIRED, country="IN")
    run(factory, ws, GateStage())
    assert get(factory, ws, company.id).status is C.HELD
    service = leads(factory, ws)
    assert service.release_policy_holds() == 0  # the rule still holds it
    switch(factory, ws, country_policy_enabled=False)
    assert service.release_policy_holds() == 1
    assert get(factory, ws, company.id).status is C.RESEARCHED
    run(factory, ws, GateStage())
    assert get(factory, ws, company.id).status is C.QUALIFIED
    # Switched back on, the next check holds it again; it is never suppressed.
    switch(factory, ws, country_policy_enabled=True)
    run(factory, ws, FakeStage("contacts", C.QUALIFIED, C.CONTACTS_FOUND, guard_policy=True))
    assert get(factory, ws, company.id).status is C.HELD


def test_a_skipped_decision_keeps_the_countrys_footer(factory: UnitOfWorkFactory, ws: str) -> None:
    company = lead(factory, ws, country="FR", rule=PolicyRule.CONSENT_REQUIRED)
    with factory(ws) as uow:
        uow.policies.upsert(CountryPolicy("FR", PolicyRule.CONSENT_REQUIRED, footer_template="F"))
        uow.commit()
    switch(factory, ws, country_policy_enabled=False)
    with factory(ws) as uow:
        decision = policy_decision_for(uow, uow.companies.get(company.id), stage="copy")
    assert (decision.outcome, decision.skipped, decision.footer_template) == (
        PolicyOutcome.ALLOW,
        True,
        "F",
    )


def test_country_rule_changes_and_removals_are_recorded(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    service = SettingsService(factory, ws)
    service.save_policy("se", PolicyRule.ALLOW_WITH_FOOTER, footer_template="x")
    service.delete_policy("SE")
    with pytest.raises(NotFound):
        service.delete_policy("SE")
    with factory(ws) as uow:
        assert uow.policies.get("SE") is None
        kinds = [e.type for e in uow.events.for_entities([(EntityType.WORKSPACE, ws)])]
    assert kinds == ["policy_changed", "policy_deleted"]
