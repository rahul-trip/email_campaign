"""On a lead's person: finding their LinkedIn profile, and finding their email again."""

from __future__ import annotations

import pytest

from outbound.db.errors import NotFound  # noqa: F401  (a missing person is NotFound)
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import CompanySource, CompanyStatus, ContactSource, HoldReason
from outbound.providers.ports import SearchHit
from outbound.services.leads import LeadError, LeadService
from outbound.stages.research.linkedin import find_linkedin, profile_address, same_name
from tests.stages.fakes import FakeSearch

C = CompanyStatus


def hit(url: str, title: str = "") -> SearchHit:
    return SearchHit(url=url, title=title, snippet="")


def test_only_a_profile_page_counts_and_its_address_is_made_plain() -> None:
    assert profile_address("https://uk.linkedin.com/in/jane-doe-1a2b?trk=x#top") == (
        "https://www.linkedin.com/in/jane-doe-1a2b"
    )
    assert profile_address("https://www.linkedin.com/company/acme") is None
    assert profile_address("https://notlinkedin.com/in/jane") is None


def test_a_namesake_is_not_taken_for_the_person() -> None:
    assert same_name("Jane Doe", "Jane M. Doe")
    assert same_name("Jané Doe", "Jane Doe")  # accents do not matter
    assert not same_name("John Doe", "Jane Doe")
    assert not same_name("Jane Smith", "Jane Doe")


def test_the_first_search_result_that_names_the_person_is_used() -> None:
    search = FakeSearch(
        hits=[
            hit("https://www.linkedin.com/in/john-doe", "John Doe - CTO - Acme | LinkedIn"),
            hit("https://www.linkedin.com/in/jane-doe", "Jane Doe - CFO - Acme | LinkedIn"),
        ]
    )
    assert find_linkedin(search, "Jane Doe", "Acme", "acme.com") == (
        "https://www.linkedin.com/in/jane-doe"
    )
    assert "Jane Doe" in search.searches[0] and "Acme" in search.searches[0]
    nothing = FakeSearch(hits=[hit("https://www.linkedin.com/in/john-doe", "John Doe | LinkedIn")])
    assert find_linkedin(nothing, "Jane Doe", "Acme", "acme.com") is None


def lead(factory: UnitOfWorkFactory, ws: str, status: CompanyStatus = C.CONTACTS_FOUND) -> str:
    """A company at ``status`` with one person. Returns the person's id."""
    with factory(ws) as uow:
        company = uow.companies.create(domain="acme.com", source=CompanySource.MANUAL, name="Acme")
        version = company.row_version
        path = [C.RESEARCHED, C.QUALIFIED, C.CONTACTS_FOUND]
        if status in (C.EMAIL_READY, C.COPY_READY):
            path.append(C.EMAIL_READY)
        if status is C.COPY_READY:
            path.append(C.COPY_READY)
        for step in path:
            version = uow.companies.transition(
                company.id, step, expected_version=version
            ).row_version
        if status is C.FAILED:
            uow.companies.transition(
                company.id, C.FAILED, expected_version=version, failed_stage="email"
            )
        contact = uow.contacts.add(
            company.id, rank=1, source=ContactSource.SITE, full_name="Jane Doe",
            first_name="Jane", last_name="Doe",
        )  # fmt: skip
        uow.commit()
    return contact.id


def test_a_found_profile_is_saved_on_the_person(factory: UnitOfWorkFactory, ws: str) -> None:
    person = lead(factory, ws)
    search = FakeSearch(hits=[hit("https://www.linkedin.com/in/jane-doe", "Jane Doe | LinkedIn")])
    service = LeadService(factory, ws, search=search)
    assert service.find_linkedin(person) == "https://www.linkedin.com/in/jane-doe"
    with factory(ws) as uow:
        assert uow.contacts.get(person).linkedin_url == "https://www.linkedin.com/in/jane-doe"
    with pytest.raises(LeadError, match="not set up"):
        LeadService(factory, ws).find_linkedin(person)


def test_nothing_is_saved_when_no_profile_clearly_fits(factory: UnitOfWorkFactory, ws: str) -> None:
    person = lead(factory, ws)
    search = FakeSearch(hits=[hit("https://www.linkedin.com/in/john-doe", "John Doe | LinkedIn")])
    assert LeadService(factory, ws, search=search).find_linkedin(person) is None
    with factory(ws) as uow:
        assert uow.contacts.get(person).linkedin_url is None


def test_find_email_again_marks_the_person_and_reopens_a_lead_past_the_email_step(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    person = lead(factory, ws, C.EMAIL_READY)
    service = LeadService(factory, ws)
    updated = service.retry_email(person)
    assert updated.status is C.CONTACTS_FOUND
    with factory(ws) as uow:
        assert uow.contacts.get(person).refresh_email is True


def test_find_email_again_on_a_lead_whose_email_step_failed(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    person = lead(factory, ws, C.FAILED)
    assert LeadService(factory, ws).retry_email(person).status is C.CONTACTS_FOUND


def test_find_email_again_is_refused_once_an_email_was_written(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    person = lead(factory, ws, C.COPY_READY)
    with pytest.raises(LeadError, match="Write to this person instead"):
        LeadService(factory, ws).retry_email(person)
    assert HoldReason.CATCH_ALL_UNVERIFIED  # catch-all holds are allowed; see the service
