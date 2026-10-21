"""Stages 3 and 4: every hold reason, the fit gate, and contact ranking."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.entities import Company, CountryPolicy
from outbound.domain.enums import (
    CompanySource,
    CompanyStatus,
    ContactSource,
    HoldReason,
    LegalEntityType,
    PolicyRule,
)
from outbound.domain.policy_seeds import DEFAULT_COUNTRY_POLICIES
from outbound.runner.guards import Guards
from outbound.runner.runner import Runner
from outbound.stages.contacts import ContactsStage
from outbound.stages.gate import GateStage

C = CompanyStatus


def seed_policies(factory: UnitOfWorkFactory, ws: str, *extra: CountryPolicy) -> None:
    with factory(ws) as uow:
        for policy in (*DEFAULT_COUNTRY_POLICIES, *extra):
            uow.policies.add_if_missing(policy)
        uow.commit()


def researched(
    factory: UnitOfWorkFactory,
    ws: str,
    *,
    domain: str = "acme.com",
    country: str | None = "GB",
    entity: LegalEntityType = LegalEntityType.CORPORATE_SUBSCRIBER,
    score: int | None = 80,
    source: CompanySource = CompanySource.DISCOVERY,
    min_score: int | None = None,
) -> str:
    with factory(ws) as uow:
        campaign_id = None
        if min_score is not None:
            campaign_id = uow.campaigns.create("c", ["CTO"], min_fit_score=min_score).id
        company = uow.companies.create(
            domain=domain, source=source, country_code=country, campaign_id=campaign_id
        )
        company = uow.companies.update_fields(
            company.id,
            {"fit_score": score, "legal_entity_type": entity},
            actor="system",
            expected_version=company.row_version,
        )
        uow.companies.transition(company.id, C.RESEARCHED, expected_version=company.row_version)
        uow.commit()
        return company.id


def run_gate(factory: UnitOfWorkFactory, ws: str) -> None:
    Runner(factory, ws, [GateStage()], Guards()).run_pipeline()


def company(factory: UnitOfWorkFactory, ws: str, company_id: str) -> Company:
    with factory(ws) as uow:
        return uow.companies.get(company_id)


# ------------------------------------------------------------------ gate: fit


def test_a_good_fit_in_an_allowed_country_is_qualified_with_the_policy_recorded(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    seed_policies(factory, ws)
    cid = researched(factory, ws)
    run_gate(factory, ws)
    after = company(factory, ws, cid)
    assert after.status is C.QUALIFIED
    assert after.policy_decision is not None
    assert after.policy_decision["outcome"] == "allow"
    assert after.policy_decision["policy_version"] == 1


def test_a_low_fit_is_disqualified_against_the_campaign_minimum(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    seed_policies(factory, ws)
    cid = researched(factory, ws, score=59, min_score=60)
    run_gate(factory, ws)
    assert company(factory, ws, cid).status is C.DISQUALIFIED


def test_the_minimum_itself_passes(factory: UnitOfWorkFactory, ws: str) -> None:
    seed_policies(factory, ws)
    cid = researched(factory, ws, score=60, min_score=60)
    run_gate(factory, ws)
    assert company(factory, ws, cid).status is C.QUALIFIED


def test_a_discovered_lead_with_no_score_is_disqualified(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    seed_policies(factory, ws)
    cid = researched(factory, ws, score=None)
    run_gate(factory, ws)
    assert company(factory, ws, cid).status is C.DISQUALIFIED


def test_a_lead_the_operator_chose_skips_the_fit_gate_but_keeps_its_score(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    seed_policies(factory, ws)
    cid = researched(factory, ws, score=5, source=CompanySource.MANUAL, min_score=60)
    run_gate(factory, ws)
    after = company(factory, ws, cid)
    assert (after.status, after.fit_score) == (C.QUALIFIED, 5)


# ------------------------------------------------------------------ gate: country policy


def test_a_country_that_forbids_cold_email_disqualifies_the_lead(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    seed_policies(factory, ws)
    cid = researched(factory, ws, domain="acme.de", country="DE")
    run_gate(factory, ws)
    after = company(factory, ws, cid)
    assert after.status is C.DISQUALIFIED
    assert after.policy_decision is not None and after.policy_decision["outcome"] == "block"


def test_an_unknown_country_holds_the_lead(factory: UnitOfWorkFactory, ws: str) -> None:
    seed_policies(factory, ws)
    cid = researched(factory, ws, country=None)
    run_gate(factory, ws)
    after = company(factory, ws, cid)
    assert (after.status, after.hold_reason) == (C.HELD, HoldReason.COUNTRY_UNKNOWN)


def test_a_uk_company_not_confirmed_as_incorporated_is_held_as_entity_unknown(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    seed_policies(factory, ws)
    cid = researched(factory, ws, entity=LegalEntityType.UNKNOWN)
    run_gate(factory, ws)
    after = company(factory, ws, cid)
    assert (after.status, after.hold_reason) == (C.HELD, HoldReason.ENTITY_UNKNOWN)


def test_a_uk_sole_trader_is_held_for_consent(factory: UnitOfWorkFactory, ws: str) -> None:
    seed_policies(factory, ws)
    cid = researched(factory, ws, entity=LegalEntityType.SOLE_TRADER_OR_PARTNERSHIP)
    run_gate(factory, ws)
    assert company(factory, ws, cid).hold_reason is HoldReason.CONSENT_REQUIRED


def test_a_country_with_no_policy_row_needs_the_operator(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    seed_policies(factory, ws)
    cid = researched(factory, ws, country="BR")
    run_gate(factory, ws)
    assert company(factory, ws, cid).hold_reason is HoldReason.NEEDS_OPERATOR


def test_a_country_that_needs_prior_consent_holds_until_it_is_recorded(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    seed_policies(factory, ws, CountryPolicy("ZA", PolicyRule.CONSENT_REQUIRED, version=1))
    cid = researched(factory, ws, country="ZA")
    run_gate(factory, ws)
    assert company(factory, ws, cid).hold_reason is HoldReason.CONSENT_REQUIRED


def test_the_policy_version_in_force_is_what_gets_recorded(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    seed_policies(factory, ws, CountryPolicy("ZA", PolicyRule.ALLOW_WITH_FOOTER, version=7))
    cid = researched(factory, ws, country="ZA")
    run_gate(factory, ws)
    decision = company(factory, ws, cid).policy_decision
    assert decision is not None and decision["policy_version"] == 7


def test_a_fit_failure_is_reported_before_the_country_is_looked_at(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = researched(factory, ws, score=1, min_score=60, country=None)  # no policies at all
    run_gate(factory, ws)
    after = company(factory, ws, cid)
    assert (after.status, after.policy_decision) == (C.DISQUALIFIED, None)


# ------------------------------------------------------------------ contacts


def qualified(factory: UnitOfWorkFactory, ws: str, titles: list[str | None]) -> str:
    seed_policies(factory, ws)
    with factory(ws) as uow:
        campaign = uow.campaigns.create("c", ["VP of Sales", "CTO"])
        company = uow.companies.create(
            domain="acme.com",
            source=CompanySource.MANUAL,
            country_code="US",
            campaign_id=campaign.id,
        )
        version = company.row_version
        for step in (C.RESEARCHED, C.QUALIFIED):
            version = uow.companies.transition(
                company.id, step, expected_version=version
            ).row_version
        for index, title in enumerate(titles, start=1):
            uow.contacts.add(
                company.id,
                rank=index,
                source=ContactSource.SITE,
                full_name=f"P{index}",
                title=title,
            )
        uow.commit()
        return company.id


def run_contacts(factory: UnitOfWorkFactory, ws: str) -> None:
    Runner(factory, ws, [ContactsStage()], Guards()).run_pipeline()


def test_candidates_are_ranked_against_the_campaigns_wanted_titles(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = qualified(factory, ws, ["Office Manager", "CTO", "VP Sales", "CEO"])
    run_contacts(factory, ws)
    with factory(ws) as uow:
        assert company(factory, ws, cid).status is C.CONTACTS_FOUND
        ranked = [(c.rank, c.title, c.seniority) for c in uow.contacts.for_company(cid)]
    assert ranked == [
        (1, "VP Sales", "vp"),
        (2, "CTO", "c_level"),
        (3, "CEO", "c_level"),
        (4, "Office Manager", "manager"),
    ]


def test_an_operator_given_person_stays_first(factory: UnitOfWorkFactory, ws: str) -> None:
    cid = qualified(factory, ws, ["CTO", "VP Sales"])
    with factory(ws) as uow:
        uow.contacts.add(
            cid, rank=3, source=ContactSource.OPERATOR, full_name="Pat", title="Analyst"
        )
        uow.commit()
    run_contacts(factory, ws)
    with factory(ws) as uow:
        assert [c.full_name for c in uow.contacts.for_company(cid)] == ["Pat", "P2", "P1"]


def test_no_candidates_fails_the_lead_with_a_readable_reason(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = qualified(factory, ws, [])
    run_contacts(factory, ws)
    after = company(factory, ws, cid)
    assert (after.status, after.failed_stage) == (C.FAILED, "contacts")
    assert "no decision-maker" in (after.last_error or "")


def test_a_policy_change_after_qualification_stops_the_lead_before_contacts(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = qualified(factory, ws, ["CTO"])
    with factory(ws) as uow:
        uow.session.execute(
            text("UPDATE country_policies SET rule = 'block' WHERE country_code = 'US'")
        )
        uow.commit()
    run_contacts(factory, ws)
    # Held for the operator, never suppressed: the rule may change back or be skipped.
    stopped = company(factory, ws, cid)
    assert (stopped.status, stopped.hold_reason) == (C.HELD, HoldReason.NEEDS_OPERATOR)


@pytest.mark.parametrize("count", [1, 5])
def test_any_number_of_candidates_is_ranked(
    factory: UnitOfWorkFactory, ws: str, count: int
) -> None:
    cid = qualified(factory, ws, ["Analyst"] * count)
    run_contacts(factory, ws)
    with factory(ws) as uow:
        assert [c.rank for c in uow.contacts.for_company(cid)] == list(range(1, count + 1))
