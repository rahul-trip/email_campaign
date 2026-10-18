from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from outbound.db.types import utcnow
from outbound.db.uow import UnitOfWork, UnitOfWorkFactory
from outbound.domain.actors import OPERATOR, provider
from outbound.domain.entities import Company, Contact, ContactEmail
from outbound.domain.enums import (
    CompanySource,
    ConsentBasis,
    ContactSource,
    ContactStatus,
    EmailStatus,
    NoteSource,
    Provenance,
)
from outbound.domain.state_machines import IllegalTransition

E = EmailStatus


def company(uow: UnitOfWork, domain: str = "acme.com") -> Company:
    return uow.companies.create(domain=domain, source=CompanySource.MANUAL)


def contact(uow: UnitOfWork, company_id: str, rank: int = 1, **kwargs: object) -> Contact:
    kwargs.setdefault("source", ContactSource.SITE)
    return uow.contacts.add(company_id, rank=rank, **kwargs)  # type: ignore[arg-type]


def email(
    uow: UnitOfWork, contact_id: str, address: str = "jane@acme.com", **kwargs: object
) -> ContactEmail:
    kwargs.setdefault("provenance", Provenance.API_DATABASE)
    return uow.emails.add(contact_id, address, **kwargs)  # type: ignore[arg-type]


# ------------------------------------------------------------------ contacts


def test_contacts_come_back_in_rank_order(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        c = company(uow)
        second = contact(uow, c.id, rank=2, full_name="Second")
        referral = contact(uow, c.id, rank=0, full_name="Referral", source=ContactSource.REFERRAL)
        first = contact(uow, c.id, rank=1, full_name="First")
        uow.commit()
        assert [x.id for x in uow.contacts.for_company(c.id)] == [referral.id, first.id, second.id]


def test_a_contact_follows_its_lifecycle(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        person = contact(uow, company(uow).id)
        assert person.status is ContactStatus.CANDIDATE
        active = uow.contacts.transition(person.id, ContactStatus.ACTIVE)
        assert active.status is ContactStatus.ACTIVE
        with pytest.raises(IllegalTransition):
            uow.contacts.transition(person.id, ContactStatus.CANDIDATE)


def test_the_engine_cannot_overwrite_an_operator_given_contact_field(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        person = contact(uow, company(uow).id, title="Co-Founder")
        uow.contacts.update_fields(person.id, {"title": "CTO"}, actor=OPERATOR)
        after = uow.contacts.update_fields(person.id, {"title": "VP"}, actor=provider("tavily"))
        assert after.title == "CTO"
        assert "title" in after.manual_fields


def test_a_linkedin_profile_belongs_to_one_contact(factory: UnitOfWorkFactory, ws: str) -> None:
    url = "https://linkedin.com/in/jane"
    with factory(ws) as uow:
        c = company(uow)
        contact(uow, c.id, linkedin_url=url)
        with pytest.raises(IntegrityError):
            contact(uow, c.id, rank=2, linkedin_url=url)


def test_many_contacts_may_have_no_linkedin_profile(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        c = company(uow)
        contact(uow, c.id, rank=1)
        contact(uow, c.id, rank=2)
        uow.commit()


# ------------------------------------------------------------------ emails


def test_addresses_are_stored_lowercase_and_found_by_address(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        person = contact(uow, company(uow).id)
        added = email(uow, person.id, "  Jane@ACME.com ")
        assert added.email == "jane@acme.com"
        assert uow.emails.by_address("JANE@acme.com") == added
        assert uow.emails.by_address("nobody@acme.com") is None


def test_one_address_belongs_to_one_contact_per_workspace(
    factory: UnitOfWorkFactory, ws: str, other_ws: str
) -> None:
    with factory(ws) as uow:
        c = company(uow)
        email(uow, contact(uow, c.id).id)
        with pytest.raises(IntegrityError):
            email(uow, contact(uow, c.id, rank=2).id)
    with factory(other_ws) as uow:  # the same address in another workspace is fine
        email(uow, contact(uow, company(uow).id).id)
        uow.commit()


def test_a_contact_has_at_most_one_primary_address(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        person = contact(uow, company(uow).id)
        first = email(uow, person.id, "a@acme.com", is_primary=True)
        second = email(uow, person.id, "b@acme.com", is_primary=True)  # replaces the first
        uow.commit()
        primaries = [e.email for e in uow.emails.for_contact(person.id) if e.is_primary]
        assert primaries == ["b@acme.com"]
        uow.emails.set_primary(first.id)
        uow.commit()
        assert [e.email for e in uow.emails.for_contact(person.id) if e.is_primary] == [
            "a@acme.com"
        ]
        assert second.id != first.id


def test_a_catch_all_walks_pending_then_resolved(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        person = contact(uow, company(uow).id)
        address = email(uow, person.id)
        pending = uow.emails.transition(
            address.id,
            E.CATCH_ALL_PENDING,
            verified_by="myemailverifier",
            resolution_ref="ticket-1",
        )
        assert pending.resolution_ref == "ticket-1" and pending.verified_at is not None
        resolved = uow.emails.transition(address.id, E.CATCH_ALL_RESOLVED, verified_by="scrubby")
        assert resolved.status is E.CATCH_ALL_RESOLVED and resolved.verified_by == "scrubby"


def test_an_invalid_address_stays_invalid(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        address = email(uow, contact(uow, company(uow).id).id)
        uow.emails.transition(address.id, E.INVALID, verified_by="hunter")
        with pytest.raises(IllegalTransition):
            uow.emails.transition(address.id, E.VALID)


def test_an_unresolved_catch_all_cannot_jump_to_valid(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        address = email(uow, contact(uow, company(uow).id).id, status=E.CATCH_ALL_UNVERIFIED)
        with pytest.raises(IllegalTransition):
            uow.emails.transition(address.id, E.VALID)


# ------------------------------------------------------------------ notes and consents


def test_notes_are_append_only_and_keep_their_order(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        c = company(uow)
        uow.notes.add(c.id, "met at Solar UK", NoteSource.OPERATOR, author="rahul")
        uow.notes.add(c.id, "asked about forecast error", NoteSource.IMPORT)
        uow.commit()
        assert [n.body for n in uow.notes.for_company(c.id)] == [
            "met at Solar UK",
            "asked about forecast error",
        ]


def test_consent_is_active_until_withdrawn(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        person = contact(uow, company(uow).id)
        assert not uow.consents.has_active(person.id)
        consent = uow.consents.add(
            person.id,
            ConsentBasis.VOLUNTARY_DISCLOSURE,
            "business card, expo, 12 Oct 2026",
            "rahul",
        )
        assert uow.consents.has_active(person.id)
        withdrawn = uow.consents.withdraw(consent.id, "rahul")
        assert withdrawn.withdrawn_at is not None and not uow.consents.has_active(person.id)
        assert utcnow() >= withdrawn.withdrawn_at
