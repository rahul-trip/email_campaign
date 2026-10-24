"""Lead queries and actions, settings, DNS checks and queued runs."""

from __future__ import annotations

import pytest

from outbound.db.errors import ConcurrencyConflict, NotFound
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.entities import Company, CountryPolicy
from outbound.domain.enums import (
    CompanySource,
    CompanyStatus,
    ConsentBasis,
    ContactSource,
    ContactStatus,
    EntityType,
    HoldReason,
    MessageState,
    PolicyRule,
    Provenance,
    RunStatus,
    SuppressionKind,
    SuppressionReason,
)
from outbound.domain.errors import InvalidInput
from outbound.domain.hashing import hash_value
from outbound.domain.policies import PolicyOutcome
from outbound.services.dns_check import check_domain
from outbound.services.leads import CONFIRMED_WORKS_HERE, LeadError, LeadService
from outbound.services.runs import RunMode, RunRequest, RunService
from outbound.services.settings import SettingsError, SettingsService
from outbound.stages.policy import policy_decision_for

C = CompanyStatus


def make(
    factory: UnitOfWorkFactory,
    ws: str,
    domain: str,
    *,
    path: tuple[CompanyStatus, ...] = (),
    hold: HoldReason | None = None,
    failed_stage: str | None = None,
    **kwargs: object,
) -> Company:
    with factory(ws) as uow:
        company = uow.companies.create(domain=domain, source=CompanySource.MANUAL, **kwargs)  # type: ignore[arg-type]
        version = company.row_version
        for step in path:
            extra: dict[str, object] = {}
            if step is C.HELD:
                extra["hold_reason"] = hold
            if step is C.FAILED:
                extra.update(failed_stage=failed_stage, last_error="boom")
            company = uow.companies.transition(
                company.id,
                step,
                expected_version=version,
                **extra,  # type: ignore[arg-type]
            )
            version = company.row_version
        uow.commit()
        return company


def leads(factory: UnitOfWorkFactory, ws: str) -> LeadService:
    return LeadService(factory, ws)


# ------------------------------------------------------------------ listing and detail


def test_leads_can_be_filtered_searched_and_paged(factory: UnitOfWorkFactory, ws: str) -> None:
    make(factory, ws, "acme.com", name="Acme Energy")
    make(factory, ws, "beta.io", path=(C.RESEARCHED,))
    make(factory, ws, "gamma.io", path=(C.RESEARCHED, C.HELD), hold=HoldReason.COUNTRY_UNKNOWN)
    service = leads(factory, ws)
    assert service.search()[1] == 3
    assert [c.domain for c in service.search(status=C.RESEARCHED)[0]] == ["beta.io"]
    held, total = service.search(hold_reason=HoldReason.COUNTRY_UNKNOWN)
    assert (total, held[0].domain) == (1, "gamma.io")
    assert [c.domain for c in service.search(text="ENERGY")[0]] == ["acme.com"]
    page, total = service.search(limit=2, offset=2)
    assert (len(page), total) == (1, 3)


def test_the_list_is_scoped_to_the_workspace(
    factory: UnitOfWorkFactory, ws: str, other_ws: str
) -> None:
    make(factory, ws, "acme.com")
    assert leads(factory, other_ws).search()[1] == 0


def test_detail_gathers_people_addresses_messages_and_notes(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    company = make(factory, ws, "acme.com")
    with factory(ws) as uow:
        contact = uow.contacts.add(company.id, rank=1, source=ContactSource.SITE, full_name="J D")
        uow.emails.add(contact.id, "j@acme.com", Provenance.API_DATABASE, is_primary=True)
        uow.commit()
    detail = leads(factory, ws).detail(company.id)
    assert detail.company.domain == "acme.com"
    assert [e.email for e in detail.contacts[0].emails] == ["j@acme.com"]


def test_detail_of_another_workspaces_lead_is_not_found(
    factory: UnitOfWorkFactory, ws: str, other_ws: str
) -> None:
    company = make(factory, ws, "acme.com")
    with pytest.raises(NotFound):
        leads(factory, other_ws).detail(company.id)


def test_the_timeline_merges_events_from_the_lead_and_its_people(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    company = make(factory, ws, "acme.com", path=(C.RESEARCHED,))
    with factory(ws) as uow:
        contact = uow.contacts.add(company.id, rank=1, source=ContactSource.SITE)
        uow.emails.add(contact.id, "j@acme.com", Provenance.API_DATABASE)
        uow.commit()
    kinds = [(e.entity_type.value, e.type) for e in leads(factory, ws).timeline(company.id)]
    assert ("company", "created") in kinds and ("company", "status_changed") in kinds
    assert ("contact", "created") in kinds and ("contact_email", "created") in kinds


def test_the_waterfall_lists_every_provider_call_for_the_lead(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    from outbound.domain.enums import CallOutcome

    company = make(factory, ws, "acme.com")
    with factory(ws) as uow:
        for provider, outcome, cost in (
            ("hunter", CallOutcome.MISS, 0),
            ("zerobounce", CallOutcome.HIT, 160_000),
        ):
            uow.calls.record(
                provider=provider,
                operation="find",
                request_hash="h",
                outcome=outcome,
                cost_micro_usd=cost,
                company_id=company.id,
            )
        uow.commit()
    steps = leads(factory, ws).waterfall(company.id)
    assert [(s.provider, s.outcome, s.cost_micro_usd) for s in steps] == [
        ("hunter", "miss", 0),
        ("zerobounce", "hit", 160_000),
    ]


# ------------------------------------------------------------------ actions


def test_editing_a_saved_target_is_version_checked(factory: UnitOfWorkFactory, ws: str) -> None:
    company = make(factory, ws, "acme.com")
    service = leads(factory, ws)
    updated = service.update(company.id, {"name": "Acme Ltd"}, expected_version=company.row_version)
    assert updated.name == "Acme Ltd" and "name" in updated.manual_fields
    with pytest.raises(ConcurrencyConflict):
        service.update(company.id, {"name": "Stale"}, expected_version=company.row_version)


def test_only_a_few_fields_can_be_edited(factory: UnitOfWorkFactory, ws: str) -> None:
    company = make(factory, ws, "acme.com")
    with pytest.raises(LeadError, match="cannot change"):
        leads(factory, ws).update(company.id, {"status": "approved"}, expected_version=1)


def test_retry_sends_a_failed_lead_back_to_the_stage_that_failed(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    company = make(factory, ws, "acme.com", path=(C.FAILED,), failed_stage="research")
    assert leads(factory, ws).retry(company.id).status is C.NEW
    with pytest.raises(LeadError, match="not failed"):
        leads(factory, ws).retry(company.id)


def test_releasing_a_hold_resumes_where_the_hold_came_from(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    company = make(
        factory, ws, "acme.com", path=(C.RESEARCHED, C.HELD), hold=HoldReason.COUNTRY_UNKNOWN
    )
    service = leads(factory, ws)
    # Nothing has changed, so releasing would only hold it again: it is refused and says why.
    with pytest.raises(LeadError, match="Nothing has changed"):
        service.release_hold(company.id)
    service.update(company.id, {"country_code": "US"}, expected_version=company.row_version)
    released = service.release_hold(company.id)
    assert (released.status, released.hold_reason) == (C.RESEARCHED, None)


def make_person(factory: UnitOfWorkFactory, ws: str, company_id: str) -> str:
    with factory(ws) as uow:
        contact = uow.contacts.add(
            company_id, rank=1, source=ContactSource.OPERATOR, full_name="A B"
        )
        uow.commit()
        return contact.id


def india_lead_held_for_consent(factory: UnitOfWorkFactory, ws: str) -> Company:
    """The real case: a lead in a consent-required country, held before any person was found."""
    with factory(ws) as uow:
        uow.policies.upsert(CountryPolicy("IN", PolicyRule.CONSENT_REQUIRED))
        uow.commit()
    return make(
        factory,
        ws,
        "tatapower.com",
        path=(C.RESEARCHED, C.HELD),
        hold=HoldReason.CONSENT_REQUIRED,
        country_code="IN",
    )


def test_releasing_a_consent_hold_is_refused_while_nobody_has_consented(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    company = india_lead_held_for_consent(factory, ws)
    service = leads(factory, ws)
    for _ in range(3):  # however many times it is tried, it is never sent round the loop
        with pytest.raises(LeadError, match="Add a person"):
            service.release_hold(company.id)
    assert service.detail(company.id).company.status is C.HELD


def test_consent_given_with_a_new_person_lets_the_release_stand_for_good(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    company = india_lead_held_for_consent(factory, ws)
    service = leads(factory, ws)
    added = service.add_person(
        company.id,
        full_name="Asha Rao",
        title="Head of Strategy",
        email="Asha.Rao@tatapower.com",
        consent_basis=ConsentBasis.EXPRESS,
        consent_evidence="Asked for a demo at the 2026 grid summit",
    )
    assert (added.contact.source, added.contact.rank) == (ContactSource.OPERATOR, 1)
    assert [(e.email, e.provenance, e.is_primary) for e in added.emails] == [
        ("asha.rao@tatapower.com", Provenance.OPERATOR_GIVEN, True)
    ]
    assert service.release_hold(company.id).status is C.RESEARCHED
    with factory(ws) as uow:  # the gate's own check now agrees, so it will not hold again
        decision = policy_decision_for(uow, uow.companies.get(company.id))
    assert decision.outcome is PolicyOutcome.ALLOW


def test_a_person_can_be_added_without_consent_or_an_address(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    company = make(factory, ws, "acme.com")
    added = leads(factory, ws).add_person(company.id, full_name="  Sam   Lee ")
    assert (added.contact.full_name, added.contact.first_name, added.contact.last_name) == (
        "Sam Lee",
        "Sam",
        "Lee",
    )
    assert added.emails == []


def test_adding_a_person_refuses_bad_input_and_blocked_addresses(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    company = make(factory, ws, "acme.com")
    service = leads(factory, ws)
    with pytest.raises(InvalidInput, match="name"):
        service.add_person(company.id, full_name="  ")
    with pytest.raises(InvalidInput, match="not an email"):
        service.add_person(company.id, full_name="Sam", email="sam-at-acme")
    with pytest.raises(InvalidInput, match="evidence"):
        service.add_person(company.id, full_name="Sam Lee", consent_basis=ConsentBasis.EXPRESS)
    with factory(ws) as uow:
        uow.suppressions.add(SuppressionKind.DOMAIN, "acme.com", SuppressionReason.OPT_OUT)
        uow.commit()
    with pytest.raises(InvalidInput, match="do-not-contact"):
        service.add_person(company.id, full_name="Sam Lee", email="sam@acme.com")
    assert leads(factory, ws).detail(company.id).contacts == []  # nothing half-saved


def test_a_one_word_name_needs_an_email_or_it_could_never_be_looked_up(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    company = make(factory, ws, "acme.com")
    service = leads(factory, ws)
    with pytest.raises(InvalidInput, match="first and a last name"):
        service.add_person(company.id, full_name="sonal")
    # With their own address the finder is not needed, so one name is enough.
    added = service.add_person(company.id, full_name="sonal", email="sonal@acme.com")
    assert added.contact.first_name == "sonal" and len(added.emails) == 1


def test_a_person_with_a_one_word_name_can_be_corrected(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    company = make(factory, ws, "acme.com")
    with factory(ws) as uow:  # as saved by an older version: one word, no address
        person = uow.contacts.add(
            company.id, rank=1, source=ContactSource.OPERATOR, full_name="sonal", first_name="sonal"
        )
        uow.commit()
    service = leads(factory, ws)
    with pytest.raises(InvalidInput, match="first and a last name"):
        service.update_person(person.id, full_name="sonal")
    fixed = service.update_person(person.id, full_name="Sonal  Mishra", title="Director")
    assert (fixed.contact.first_name, fixed.contact.last_name, fixed.contact.title) == (
        "Sonal",
        "Mishra",
        "Director",
    )
    assert "full_name" in fixed.contact.manual_fields  # the engine will not overwrite it
    with_address = service.update_person(person.id, email="Sonal@acme.com")
    assert [e.email for e in with_address.emails] == ["sonal@acme.com"]
    replaced = service.update_person(person.id, email="other@acme.com")
    # The new address is the one written to; the old one stays as history.
    assert [(e.email, e.is_primary) for e in replaced.emails] == [
        ("other@acme.com", True),
        ("sonal@acme.com", False),
    ]


def test_a_person_cannot_be_added_to_another_workspaces_lead(
    factory: UnitOfWorkFactory, ws: str, other_ws: str
) -> None:
    company = make(factory, other_ws, "acme.com")
    with pytest.raises(NotFound):
        leads(factory, ws).add_person(company.id, full_name="Sam Lee")
    person = make_person(factory, other_ws, company.id)
    with pytest.raises(NotFound):
        leads(factory, ws).update_person(person, full_name="Sam Lee")


def test_a_hold_with_no_default_needs_the_operator_to_choose(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    company = make(
        factory,
        ws,
        "acme.com",
        path=(C.RESEARCHED, C.HELD),
        hold=HoldReason.NEEDS_OPERATOR,
    )
    service = leads(factory, ws)
    with pytest.raises(LeadError, match="no default"):
        service.release_hold(company.id)
    assert service.release_hold(company.id, resume_to=C.RESEARCHED).status is C.RESEARCHED


def test_a_lead_that_is_not_held_cannot_be_released(factory: UnitOfWorkFactory, ws: str) -> None:
    company = make(factory, ws, "acme.com")
    with pytest.raises(LeadError, match="not held"):
        leads(factory, ws).release_hold(company.id)


def test_a_resume_target_the_lifecycle_forbids_is_refused(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    company = make(
        factory, ws, "acme.com", path=(C.RESEARCHED, C.HELD), hold=HoldReason.NEEDS_OPERATOR
    )
    with pytest.raises(LeadError, match="cannot move"):
        leads(factory, ws).release_hold(company.id, resume_to=C.COPY_READY)


def test_a_disqualified_lead_can_be_requalified_by_the_operator(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    company = make(factory, ws, "acme.com", path=(C.RESEARCHED, C.DISQUALIFIED))
    assert leads(factory, ws).requalify(company.id).status is C.QUALIFIED
    with pytest.raises(LeadError, match="not disqualified"):
        leads(factory, ws).requalify(company.id)


def test_consent_needs_its_evidence_and_is_recorded(factory: UnitOfWorkFactory, ws: str) -> None:
    company = make(factory, ws, "acme.com")
    with factory(ws) as uow:
        contact = uow.contacts.add(company.id, rank=1, source=ContactSource.SITE)
        uow.commit()
    service = leads(factory, ws)
    with pytest.raises(LeadError, match="evidence"):
        service.record_consent(contact.id, ConsentBasis.EXPRESS, " ")
    consent = service.record_consent(contact.id, ConsentBasis.EXPRESS, "replied yes on 2026-10-01")
    assert consent.active
    with factory(ws) as uow:
        assert uow.consents.has_active(contact.id)


def test_recording_the_same_consent_twice_keeps_one(factory: UnitOfWorkFactory, ws: str) -> None:
    company = make(factory, ws, "rebase.energy")
    with factory(ws) as uow:
        contact = uow.contacts.add(company.id, rank=2, source=ContactSource.SITE)
        uow.commit()
    service = leads(factory, ws)
    first = service.record_consent(contact.id, ConsentBasis.EXPRESS, "said yes")
    again = service.record_consent(contact.id, ConsentBasis.EXPRESS, "said yes again")
    assert again.id == first.id
    with factory(ws) as uow:
        assert len(uow.consents.for_contact(contact.id)) == 1
        assert uow.contacts.get(contact.id).rank == 1  # the person who consented comes first


def rebase(factory: UnitOfWorkFactory, ws: str) -> tuple[Company, str, str]:
    """The real case: a CTO found by a finder, and the CEO the operator gave consent for."""
    with factory(ws) as uow:
        uow.policies.upsert(CountryPolicy("SE", PolicyRule.CONSENT_REQUIRED))
        uow.commit()
    company = make(
        factory, ws, "rebase.energy", path=(C.RESEARCHED, C.QUALIFIED), country_code="SE"
    )
    with factory(ws) as uow:
        cto = uow.contacts.add(
            company.id, rank=1, source=ContactSource.SITE, full_name="Mihai Chiru"
        )
        ceo = uow.contacts.add(
            company.id, rank=2, source=ContactSource.SITE, full_name="Sebastian Haglund"
        )
        uow.emails.add(cto.id, "mihai@rebase.energy", Provenance.API_DATABASE, is_primary=True)
        uow.consents.add(ceo.id, ConsentBasis.EXPRESS, "met at a conference", "operator")
        uow.commit()
    return company, cto.id, ceo.id


def test_someone_elses_consent_does_not_allow_writing_to_this_person(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    company, cto, ceo = rebase(factory, ws)
    with factory(ws) as uow:
        current = uow.companies.get(company.id)
        # Before a recipient is known, anyone's consent keeps the lead moving...
        assert policy_decision_for(uow, current).outcome is PolicyOutcome.ALLOW
        # ...but once the recipient is named, only their own consent counts.
        assert policy_decision_for(uow, current, recipient_id=ceo).outcome is PolicyOutcome.ALLOW
        to_cto = policy_decision_for(uow, current, recipient_id=cto)
    assert (to_cto.outcome, to_cto.hold_reason) == (
        PolicyOutcome.HOLD,
        HoldReason.CONSENT_REQUIRED,
    )


def test_adding_the_same_person_again_updates_them_instead_of_a_second_card(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    company = make(factory, ws, "tilt-energy.com")
    service = leads(factory, ws)
    first = service.add_person(company.id, full_name="Romain", email="romain@tilt-energy.com")
    again = service.add_person(
        company.id, full_name="Romain Serres", title="CEO", email="romain.serres@tilt-energy.com"
    )
    assert again.contact.id == first.contact.id
    assert (again.contact.full_name, again.contact.title) == ("Romain Serres", "CEO")
    assert [(e.email, e.is_primary) for e in again.emails] == [
        ("romain.serres@tilt-energy.com", True),
        ("romain@tilt-energy.com", False),
    ]
    with factory(ws) as uow:
        assert len(uow.contacts.for_company(company.id)) == 1


def test_a_person_added_after_ranking_is_put_first(factory: UnitOfWorkFactory, ws: str) -> None:
    company = make(factory, ws, "acme.com")
    with factory(ws) as uow:
        for rank in (1, 2):
            uow.contacts.add(
                company.id, rank=rank, source=ContactSource.SITE, full_name=f"P {rank}"
            )
        uow.commit()
    added = leads(factory, ws).add_person(company.id, full_name="Asha Rao")
    with factory(ws) as uow:
        people = uow.contacts.for_company(company.id)
    assert (people[0].id, people[0].rank) == (added.contact.id, 1)
    assert [p.rank for p in people] == [1, 2, 3]


def test_a_person_matched_by_mistake_can_be_removed(factory: UnitOfWorkFactory, ws: str) -> None:
    company = make(factory, ws, "amperon.co")
    with factory(ws) as uow:
        wrong = uow.contacts.add(
            company.id,
            rank=1,
            source=ContactSource.SEARCH,
            full_name="Dan Roth",
            linkedin_url="https://www.linkedin.com/in/danielproth",
        )
        uow.commit()
    service = leads(factory, ws)
    service.remove_person(wrong.id)
    with factory(ws) as uow:
        assert uow.contacts.for_company(company.id) == []
        removed = [e.type for e in uow.events.for_entities([(EntityType.COMPANY, company.id)])]
    assert "person_removed" in removed


def test_a_person_already_written_to_cannot_be_removed(factory: UnitOfWorkFactory, ws: str) -> None:
    company, cto, _ = rebase(factory, ws)
    with factory(ws) as uow:
        address = uow.emails.for_contact(cto)[0]
        uow.messages.create(
            company_id=company.id,
            contact_id=cto,
            contact_email_id=address.id,
            step=0,
            subject="hello",
            generated_body="body",
        )
        uow.commit()
    with pytest.raises(LeadError, match="already been written"):
        leads(factory, ws).remove_person(cto)


def test_the_draft_can_be_moved_to_another_person(factory: UnitOfWorkFactory, ws: str) -> None:
    company, cto, ceo = rebase(factory, ws)
    with factory(ws) as uow:
        current = uow.companies.get(company.id)
        version = current.row_version
        for step in (C.CONTACTS_FOUND, C.EMAIL_READY, C.COPY_READY):
            version = uow.companies.transition(
                company.id, step, expected_version=version
            ).row_version
        address = uow.emails.for_contact(cto)[0]
        draft = uow.messages.create(
            company_id=company.id,
            contact_id=cto,
            contact_email_id=address.id,
            step=0,
            subject="hello",
            generated_body="body",
        )
        uow.commit()
    moved = leads(factory, ws).change_recipient(company.id, ceo)
    assert moved.status is C.CONTACTS_FOUND
    with factory(ws) as uow:
        assert uow.messages.get(draft.id).state is MessageState.CANCELLED
        assert uow.contacts.for_company(company.id)[0].id == ceo


def test_a_person_a_search_could_not_place_is_confirmed_by_the_operator(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    company = make(factory, ws, "volue.com")
    with factory(ws) as uow:
        person = uow.contacts.add(
            company.id,
            rank=1,
            source=ContactSource.SEARCH,
            full_name="Sam Lee",
            status=ContactStatus.UNCONFIRMED,
        )
        uow.commit()
    service = leads(factory, ws)
    confirmed = service.confirm_person(person.id)
    assert confirmed.contact.status is ContactStatus.CANDIDATE
    with pytest.raises(LeadError, match="not waiting"):
        service.confirm_person(person.id)
    with factory(ws) as uow:
        (event,) = [
            e
            for e in uow.events.for_entities([(EntityType.CONTACT, person.id)])
            if e.type == "status_changed"
        ]
    assert (event.actor, event.data["reason"]) == ("operator", CONFIRMED_WORKS_HERE)


# ------------------------------------------------------------------ settings


def settings(factory: UnitOfWorkFactory, ws: str, **kwargs: object) -> SettingsService:
    return SettingsService(factory, ws, **kwargs)  # type: ignore[arg-type]


def test_the_sender_profile_is_merged_not_replaced(factory: UnitOfWorkFactory, ws: str) -> None:
    service = settings(factory, ws)
    service.update_sender_profile({"legal_name": "Quantra Ltd", "postal_address": "1 High St"})
    service.update_sender_profile({"signature_name": "Sam"})
    profile = service.sender_profile()
    assert (profile["legal_name"], profile["signature_name"]) == ("Quantra Ltd", "Sam")
    with pytest.raises(SettingsError, match="unknown"):
        service.update_sender_profile({"favourite_colour": "teal"})


def test_automatic_sending_cannot_be_switched_on_yet(factory: UnitOfWorkFactory, ws: str) -> None:
    service = settings(factory, ws)
    with pytest.raises(SettingsError, match="Phase 5"):
        service.update_workspace_settings({"send_enabled": True})
    assert service.update_workspace_settings({"few_shot_examples": 3})["few_shot_examples"] == 3
    with pytest.raises(SettingsError, match="cannot change"):
        service.update_workspace_settings({"breaker": {}})


def test_campaigns_are_created_and_changed(factory: UnitOfWorkFactory, ws: str) -> None:
    service = settings(factory, ws)
    created = service.create_campaign("expo", ["CTO"], min_fit_score=70)
    assert created.min_fit_score == 70
    with pytest.raises(SettingsError, match="already exists"):
        service.create_campaign("expo", ["CEO"])
    with pytest.raises(SettingsError, match="at least one"):
        service.create_campaign("empty", [])
    updated = service.update_campaign(created.id, {"research_questions": ["Do they trade?"]})
    assert updated.research_questions == ("Do they trade?",)
    with pytest.raises(SettingsError, match="cannot change"):
        service.update_campaign(created.id, {"status": "x"})


def test_a_policy_change_bumps_the_version_and_an_unchanged_save_does_not(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    service = settings(factory, ws)
    first = service.save_policy("gb", PolicyRule.ALLOW_WITH_FOOTER, footer_template="Footer")
    assert (first.country_code, first.version) == ("GB", 1)
    again = service.save_policy("GB", PolicyRule.ALLOW_WITH_FOOTER, footer_template="Footer")
    assert again.version == 1
    changed = service.save_policy("GB", PolicyRule.BLOCK, reviewer="lawyer@firm")
    assert changed.version == 2
    with factory(ws) as uow:
        stored = uow.policies.get("GB")
    assert stored is not None and stored.reviewed_by == "lawyer@firm"
    with pytest.raises(SettingsError, match="two-letter"):
        service.save_policy("GBR", PolicyRule.BLOCK)


def test_suppressions_are_hashed_and_only_a_fingerprint_is_shown(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    service = settings(factory, ws)
    assert service.suppress(SuppressionKind.EMAIL, "Jane@Acme.com", SuppressionReason.OPT_OUT)
    assert not service.suppress(SuppressionKind.EMAIL, "jane@acme.com", SuppressionReason.OPT_OUT)
    [entry] = service.suppressions()
    assert entry.fingerprint == hash_value("jane@acme.com")[:10]
    assert "acme" not in repr(entry)
    with pytest.raises(SettingsError):
        service.suppress(SuppressionKind.EMAIL, " ", SuppressionReason.OPT_OUT)


def test_a_mailbox_dns_check_is_run_and_stored(factory: UnitOfWorkFactory, ws: str) -> None:
    records = {
        "quantra.example": ["v=spf1 include:_spf.google.com ~all"],
        "google._domainkey.quantra.example": ["v=DKIM1; k=rsa; p=ABC"],
        "_dmarc.quantra.example": ["v=DMARC1; p=quarantine"],
    }
    service = settings(factory, ws, dns_lookup=lambda name: records.get(name, []))
    with factory(ws) as uow:
        box = uow.mailboxes.create("Sam@Quantra.example", "Quantra.example")
        uow.commit()
    assert (box.address, box.sending_domain) == ("sam@quantra.example", "quantra.example")
    report = service.dns_check(box.id)
    assert report["ok"] is True
    with factory(ws) as uow:
        assert uow.mailboxes.get(box.id).dns_check == report


def test_dns_problems_are_reported_in_plain_words() -> None:
    records = {
        "bad.example": ["v=spf1 a ~all", "v=spf1 mx ~all"],
        "_dmarc.bad.example": ["v=DMARC1; p=none"],
    }
    report = check_domain("Bad.Example", lambda name: records.get(name, []))
    assert not report.ok
    assert "more than one SPF" in report.spf.detail
    assert "no DKIM key" in report.dkim.detail
    assert report.dmarc.ok and "monitoring only" in report.dmarc.detail
    assert check_domain("nothing.example", lambda name: []).spf.detail.startswith("no SPF")


# ------------------------------------------------------------------ runs


def test_a_run_is_queued_then_claimed_once_then_cancelled_or_finished(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    runs = RunService(factory, ws)
    queued = runs.queue(RunRequest(limit=5, mode=RunMode.MIXED, discover=3))
    assert queued.status is RunStatus.QUEUED
    assert RunRequest.from_params(queued.params) == RunRequest(
        limit=5, mode=RunMode.MIXED, discover=3
    )
    with factory(ws) as uow:
        claimed = uow.runs.claim_next()
        uow.commit()
        assert claimed is not None and claimed.id == queued.id
        assert uow.runs.claim_next() is None
    assert runs.get(queued.id).status is RunStatus.RUNNING
    assert runs.cancel(queued.id).status is RunStatus.CANCELLED


def test_cancelling_a_queued_run_stops_it_before_it_starts(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    runs = RunService(factory, ws)
    queued = runs.queue(RunRequest())
    assert runs.cancel(queued.id).status is RunStatus.CANCELLED
    with factory(ws) as uow:
        assert uow.runs.claim_next() is None


def test_a_cancelled_run_is_not_overwritten_when_it_finishes(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    runs = RunService(factory, ws)
    queued = runs.queue(RunRequest())
    with factory(ws) as uow:
        uow.runs.claim_next()
        uow.commit()
    runs.cancel(queued.id)
    with factory(ws) as uow:
        uow.runs.finish(queued.id, RunStatus.SUCCEEDED, {"research": {"advanced": 1}})
        uow.commit()
    final = runs.get(queued.id)
    assert final.status is RunStatus.CANCELLED and final.counts == {"research": {"advanced": 1}}


def test_recent_runs_are_listed_newest_first(factory: UnitOfWorkFactory, ws: str) -> None:
    runs = RunService(factory, ws)
    first = runs.queue(RunRequest(limit=1))
    second = runs.queue(RunRequest(limit=2))
    assert [r.id for r in runs.recent()] == [second.id, first.id]


def test_every_save_of_the_profile_records_a_review_the_client_cannot_forge(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    service = settings(factory, ws)
    assert "reviewed_at" not in service.sender_profile()
    saved = service.update_sender_profile({"legal_name": "Quantra", "reviewed_at": "1999-01-01"})
    assert saved["reviewed_at"] != "1999-01-01"
    assert saved["reviewed_at"].startswith("20")


def test_a_new_workspace_ships_no_claims_for_the_writer_to_quote() -> None:
    from outbound.services.defaults import default_sender_profile

    profile = default_sender_profile()
    assert profile["value_propositions"] == [] and profile["case_studies"] == []
    text = str(profile["narrative"])
    assert "%" not in text and "GBP" not in text and "proven" not in text.lower()
    assert "reviewed_at" not in profile and profile["signature_name"].startswith("[")


def test_the_first_email_length_is_a_setting_and_cannot_be_back_to_front(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    service = settings(factory, ws)
    assert (
        service.update_workspace_settings({"email_min_words": 100, "email_max_words": 160})[
            "email_max_words"
        ]
        == 160
    )
    with pytest.raises(SettingsError, match="cannot be longer"):
        service.update_workspace_settings({"email_min_words": 300})  # above the saved maximum
    assert service.workspace_settings()["email_min_words"] == 100  # the refusal changed nothing


def test_how_you_write_is_part_of_the_sender_profile(factory: UnitOfWorkFactory, ws: str) -> None:
    service = settings(factory, ws)
    saved = service.update_sender_profile(
        {
            "greeting": "Dear",
            "outreach_goal": "explore a partnership",
            "style_examples": ["Dear Ted, ..."],
        }
    )
    assert (saved["greeting"], saved["outreach_goal"], saved["style_examples"]) == (
        "Dear",
        "explore a partnership",
        ["Dear Ted, ..."],
    )


def test_research_again_cancels_the_waiting_email_and_starts_the_lead_over(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    company, cto, _ = rebase(factory, ws)
    with factory(ws) as uow:
        version = uow.companies.get(company.id).row_version
        for step in (C.CONTACTS_FOUND, C.EMAIL_READY, C.COPY_READY):
            version = uow.companies.transition(
                company.id, step, expected_version=version
            ).row_version
        address = uow.emails.for_contact(cto)[0]
        draft = uow.messages.create(
            company_id=company.id,
            contact_id=cto,
            contact_email_id=address.id,
            step=0,
            subject="hello",
            generated_body="body",
        )
        uow.commit()
    service = leads(factory, ws)
    assert service.research_again(company.id).status is C.NEW
    with factory(ws) as uow:
        assert uow.messages.get(draft.id).state is MessageState.CANCELLED
        assert len(uow.contacts.for_company(company.id)) == 2  # people and addresses are kept
    with pytest.raises(LeadError, match="not been researched yet"):
        service.research_again(company.id)


def test_a_lead_whose_email_has_left_is_not_researched_again(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    company = make(
        factory,
        ws,
        "sent.com",
        path=(
            C.RESEARCHED,
            C.QUALIFIED,
            C.CONTACTS_FOUND,
            C.EMAIL_READY,
            C.COPY_READY,
            C.APPROVED,
            C.IN_SEQUENCE,
        ),
    )
    with pytest.raises(LeadError, match="already left"):
        leads(factory, ws).research_again(company.id)


# ------------------------------------------------------------------ the DNS check, in depth


def txt(records: dict[str, list[str]]):  # type: ignore[no-untyped-def]
    return lambda name: records.get(name, [])


def test_spf_lookups_are_counted_through_includes_and_the_limit_is_enforced() -> None:
    from outbound.services.dns_check import spf_lookups

    records = {
        "_spf.google.com": ["v=spf1 include:_netblocks.google.com ~all"],
        "_netblocks.google.com": ["v=spf1 ip4:1.2.3.4 ~all"],
    }
    assert spf_lookups("v=spf1 include:_spf.google.com mx -all", txt(records)) == 3
    greedy = "v=spf1 " + " ".join(f"include:s{i}.example" for i in range(11)) + " -all"
    report = check_domain("a.example", txt({"a.example": [greedy]}))
    assert not report.spf.ok and "11 DNS lookups" in report.spf.detail
    ok = check_domain(
        "a.example", txt({"a.example": ["v=spf1 include:_spf.google.com ~all"], **records})
    )
    assert ok.spf.ok and "2 of 10 lookups" in ok.spf.detail


def test_the_providers_own_dkim_selector_is_tried_first_and_a_given_one_is_added() -> None:
    domain_key = {"selector2._domainkey.q.example": ["v=DKIM1; p=XYZ"]}
    graph = check_domain("q.example", txt(domain_key), gateway="graph")
    assert graph.dkim.ok and "selector2" in graph.dkim.detail
    custom = check_domain(
        "q.example", txt({"mine._domainkey.q.example": ["v=DKIM1; p=A"]}), ["mine"]
    )
    assert custom.dkim.ok and "mine" in custom.dkim.detail
    assert not check_domain("q.example", txt({})).dkim.ok


def test_mx_is_checked_only_when_it_can_be_looked_up() -> None:
    assert check_domain("q.example", txt({})).mx is None
    none = check_domain("q.example", txt({}), mx_lookup=lambda _: [])
    assert none.mx is not None and not none.mx.ok and "replies" in none.mx.detail
    some = check_domain("q.example", txt({}), mx_lookup=lambda _: ["aspmx.l.google.com"])
    assert some.mx is not None and some.mx.ok and "mx" in some.to_json()


def test_dmarc_without_report_address_says_how_to_get_reports() -> None:
    plain = check_domain("q.example", txt({"_dmarc.q.example": ["v=DMARC1; p=quarantine"]})).dmarc
    assert plain.ok and "rua=" in plain.detail
    full = check_domain(
        "q.example", txt({"_dmarc.q.example": ["v=DMARC1; p=reject; rua=mailto:r@q.example"]})
    ).dmarc
    assert full.ok and "rua" not in full.detail
    assert "rua=mailto:dmarc@q.example" in check_domain("q.example", txt({})).dmarc.detail
