"""Skipping the email check (even past an *invalid* answer), and confirming it at approval."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.entities import Company
from outbound.domain.enums import (
    CompanySource,
    CompanyStatus,
    ContactSource,
    ContactStatus,
    EmailStatus,
    EntityType,
    MessageState,
    PolicyStage,
    Provenance,
    SuppressionKind,
    SuppressionReason,
)
from outbound.domain.errors import InvalidInput
from outbound.domain.policy_seeds import DEFAULT_COUNTRY_POLICIES
from outbound.services.leads import LeadError, LeadService
from outbound.services.review import ReviewError, ReviewService
from tests.db.test_email_stage import Finder, Verifier, run_stage
from tests.db.test_review_and_deliver import copy_ready

C = CompanyStatus


def tilt(factory: UnitOfWorkFactory, ws: str, status: EmailStatus) -> tuple[Company, str]:
    """The real case: the operator's guess at the CEO's address came back unknown."""
    with factory(ws) as uow:
        for policy in DEFAULT_COUNTRY_POLICIES:
            uow.policies.add_if_missing(policy)
        company = uow.companies.create(
            domain="tilt-energy.com", source=CompanySource.MANUAL, country_code="FR"
        )
        version = company.row_version
        for step in (C.RESEARCHED, C.QUALIFIED, C.CONTACTS_FOUND, C.FAILED):
            extra = (
                {"failed_stage": "email", "last_error": "no valid email"}
                if step is C.FAILED
                else {}
            )
            company = uow.companies.transition(
                company.id,
                step,
                expected_version=version,
                **extra,  # type: ignore[arg-type]
            )
            version = company.row_version
        person = uow.contacts.add(
            company.id,
            rank=1,
            source=ContactSource.OPERATOR,
            full_name="Romain",
            first_name="Romain",
            status=ContactStatus.ACTIVE,
        )
        address = uow.emails.add(
            person.id,
            "romain@tilt-energy.com",
            Provenance.OPERATOR_GIVEN,
            status=status,
            is_primary=True,
        )
        uow.commit()
        return company, address.id


def get(factory: UnitOfWorkFactory, ws: str, company_id: str) -> Company:
    with factory(ws) as uow:
        return uow.companies.get(company_id)


@pytest.mark.parametrize("status", [EmailStatus.UNKNOWN, EmailStatus.INVALID])
def test_a_lead_stuck_on_an_unproven_address_goes_on_once_the_check_is_skipped(
    factory: UnitOfWorkFactory, ws: str, status: EmailStatus
) -> None:
    company, email_id = tilt(factory, ws, status)
    service = LeadService(factory, ws)
    with pytest.raises(InvalidInput, match="say why"):
        service.skip_email_verification(email_id, " ")
    person = service.skip_email_verification(email_id, "I have written to Romain there before")
    assert person.emails[0].verification_skipped is True
    assert get(factory, ws, company.id).status is C.CONTACTS_FOUND
    verifier = Verifier({})
    finder = Finder("hunter", {})
    run_stage(factory, ws, [finder], verifier)
    assert get(factory, ws, company.id).status is C.EMAIL_READY
    assert verifier.checked == [] and finder.calls == []  # nothing paid for
    with factory(ws) as uow:
        events = uow.events.for_entities([(EntityType.CONTACT_EMAIL, email_id)])
    (event,) = [e for e in events if e.type == "email_verification_skipped"]
    assert (event.actor, event.data["status"]) == ("operator", status.value)


def test_a_suppressed_address_cannot_skip_the_check(factory: UnitOfWorkFactory, ws: str) -> None:
    _, email_id = tilt(factory, ws, EmailStatus.UNKNOWN)
    with factory(ws) as uow:
        uow.suppressions.add(
            SuppressionKind.EMAIL, "romain@tilt-energy.com", SuppressionReason.OPT_OUT
        )
        uow.commit()
    with pytest.raises(LeadError, match="do-not-contact"):
        LeadService(factory, ws).skip_email_verification(email_id, "known")


def skipped_review(factory: UnitOfWorkFactory, ws: str) -> tuple[str, str, str]:
    cid, mid = copy_ready(factory, ws)
    with factory(ws) as uow:
        message = uow.messages.get(mid)
        uow.emails.set_verification_skipped(
            message.contact_email_id, True, actor="operator", reason="known"
        )
        uow.commit()
    return cid, mid, message.contact_email_id


def test_approving_an_email_that_relies_on_a_skipped_check_needs_a_confirmation(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    _, mid, _ = skipped_review(factory, ws)
    review = ReviewService(factory, ws)
    [item] = review.queue()
    assert [s.kind for s in item.skips] == ["email_verification"]
    with pytest.raises(ReviewError, match="checks you skipped"):
        review.approve(mid)
    approved = review.approve(mid, acknowledge_skips=True)
    assert approved.state is MessageState.APPROVED
    with factory(ws) as uow:
        events = uow.events.for_entities([(EntityType.MESSAGE, mid)])
    assert [e.data for e in events if e.type == "approved_with_skips"] == [
        {"skips": ["email_verification"]}
    ]


def test_every_kind_of_skip_is_listed_for_review(factory: UnitOfWorkFactory, ws: str) -> None:
    cid, mid, _ = skipped_review(factory, ws)
    with factory(ws) as uow:
        message = uow.messages.get(mid)
        contact = uow.contacts.add(
            cid, rank=2, source=ContactSource.SEARCH, status=ContactStatus.UNCONFIRMED
        )
        uow.commit()
    LeadService(factory, ws).skip_policy(cid, PolicyStage.DELIVER, "they asked")
    LeadService(factory, ws).confirm_person(contact.id)
    with factory(ws) as uow:  # the email is to the person the operator confirmed
        uow.session.execute(
            text("UPDATE messages SET contact_id = :c WHERE id = :m"),
            {"c": contact.id, "m": message.id},
        )
        uow.commit()
    [item] = ReviewService(factory, ws).queue()
    assert sorted(s.kind for s in item.skips) == [
        "country_policy",
        "email_verification",
        "works_here",
    ]


def test_an_address_on_the_do_not_contact_list_is_refused_at_approval(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    _, mid = copy_ready(factory, ws)
    with factory(ws) as uow:
        uow.suppressions.add(SuppressionKind.DOMAIN, "acme.com", SuppressionReason.OPT_OUT)
        uow.commit()
    with pytest.raises(ReviewError, match="do-not-contact"):
        ReviewService(factory, ws).approve(mid)


def test_the_check_can_be_restored_until_the_email_is_approved(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    _, mid, email_id = skipped_review(factory, ws)
    service = LeadService(factory, ws)
    assert service.restore_email_verification(email_id).emails[0].verification_skipped is False
    service.skip_email_verification(email_id, "known")
    ReviewService(factory, ws).approve(mid, acknowledge_skips=True)
    with pytest.raises(LeadError, match="Reject it"):
        service.restore_email_verification(email_id)
