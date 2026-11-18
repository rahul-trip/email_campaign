"""On a lead's person: finding their LinkedIn profile, and finding their email again."""

from __future__ import annotations

import pytest

from outbound.db.errors import NotFound  # noqa: F401  (a missing person is NotFound)
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import CompanySource, CompanyStatus, ContactSource, HoldReason
from outbound.providers.ports import SearchHit
from outbound.services.leads import LeadError, LeadService
from outbound.stages.research.linkedin import (
    find_linkedin,
    profile_address,
    same_name,
    similar_name,
)
from tests.stages.fakes import FakeSearch

C = CompanyStatus


def hit(url: str, title: str = "", snippet: str = "") -> SearchHit:
    return SearchHit(url=url, title=title, snippet=snippet)


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


def test_the_search_uses_the_company_name_without_inc_or_ltd() -> None:
    # Seen on daxa.ai: '"Daxa inc"' as an exact phrase found nobody; profiles say "Daxa".
    search = FakeSearch(
        hits=[hit("https://www.linkedin.com/in/jane-doe", "Jane Doe - CTO - Daxa | LinkedIn")]
    )
    assert find_linkedin(search, "Jane Doe", "Daxa inc", "daxa.ai") == (
        "https://www.linkedin.com/in/jane-doe"
    )
    assert '"Daxa"' in search.searches[0] and "inc" not in search.searches[0]
    only_noise = FakeSearch()
    find_linkedin(only_noise, "Jane Doe", "Ltd.", "acme.com")
    assert '"acme.com"' in only_noise.searches[0]  # nothing left of the name: the website


def test_a_namesake_whose_profile_names_another_company_or_none_is_not_taken() -> None:
    # Seen on Vibrant Labs: eight "Jithin James" profiles, none at Vibrant Labs; the first (a
    # data analyst at "Gapblue Software Labs") was saved because "Labs" matched.
    search = FakeSearch(
        hits=[
            hit(
                "https://www.linkedin.com/in/jithin-james-1",
                "Jithin James - Data Science|| Power BI - Gapblue Software Labs Pvt Ltd | LinkedIn",
                "Data Analyst with 4+ years in Bengaluru",
            ),
            hit("https://www.linkedin.com/in/jithin-james-2", "Jithin James | LinkedIn",
                "Sales Manager at 42 Estates"),
        ]
    )  # fmt: skip
    assert find_linkedin(search, "Jithin James", "Vibrant Labs", "vibrantlabs.com") is None


def test_a_profile_that_mentions_the_company_only_in_its_snippet_is_taken() -> None:
    search = FakeSearch(
        hits=[
            hit("https://www.linkedin.com/in/jithin-james-9", "Jithin James | LinkedIn",
                "## Experience - Co-founder at Vibrant Labs (2023 to present)"),
        ]
    )  # fmt: skip
    assert find_linkedin(search, "Jithin James", "Vibrant Labs", "vibrantlabs.com") == (
        "https://www.linkedin.com/in/jithin-james-9"
    )


def test_a_one_letter_spelling_difference_is_taken_only_with_the_company_named() -> None:
    # Seen on daxa.ai: entered "Shridhar", the profile says "Sridhar".
    right = FakeSearch(
        hits=[
            hit("https://www.linkedin.com/in/sridhar-r", "Sridhar Ramaswamy - Co-founder & CTO at "
                "Daxa AI - LinkedIn")
        ]
    )  # fmt: skip
    assert find_linkedin(right, "Shridhar ramaswamy", "Daxa inc", "daxa.ai") == (
        "https://www.linkedin.com/in/sridhar-r"
    )
    elsewhere = FakeSearch(
        hits=[hit("https://www.linkedin.com/in/sridhar-x", "Sridhar Ramaswamy | LinkedIn",
                  "Engineer at Snowflake")]
    )  # fmt: skip
    assert find_linkedin(elsewhere, "Shridhar ramaswamy", "Daxa inc", "daxa.ai") is None
    assert similar_name("Mohammed Ali", "Mohammad Ali")
    assert not similar_name("John Doe", "Jane Doe")  # four letters, two apart
    assert not similar_name("Sridhar Raman", "Shridhar Ramaswamy")  # another surname


def lead(
    factory: UnitOfWorkFactory,
    ws: str,
    status: CompanyStatus = C.CONTACTS_FOUND,
    domain: str = "acme.com",
) -> str:
    """A company at ``status`` with one person. Returns the person's id."""
    with factory(ws) as uow:
        company = uow.companies.create(domain=domain, source=CompanySource.MANUAL, name="Acme")
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
    search = FakeSearch(
        hits=[hit("https://www.linkedin.com/in/jane-doe", "Jane Doe - CTO at Acme | LinkedIn")]
    )
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


def held_on_catch_all(factory: UnitOfWorkFactory, ws: str) -> tuple[str, str]:
    """A lead held as catch-all unverified. Returns the company's and the person's ids."""
    person = lead(factory, ws, C.CONTACTS_FOUND)
    with factory(ws) as uow:
        company = uow.companies.get(uow.contacts.get(person).company_id)
        uow.companies.transition(
            company.id,
            C.HELD,
            expected_version=company.row_version,
            hold_reason=HoldReason.CATCH_ALL_UNVERIFIED,
        )
        uow.commit()
    return company.id, person


def test_find_email_again_for_many_leads_reopens_each_held_one_and_skips_the_rest(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    held_company, person = held_on_catch_all(factory, ws)
    other = lead(factory, ws, C.COPY_READY, "other.com")
    with factory(ws) as uow:
        other_company = uow.contacts.get(other).company_id
    asked, skipped = LeadService(factory, ws).retry_email_for_companies(
        [held_company, held_company, other_company, "no-such-lead"]
    )
    assert (asked, skipped) == (1, 2)
    with factory(ws) as uow:
        assert uow.companies.get(held_company).status is C.CONTACTS_FOUND
        assert uow.contacts.get(person).refresh_email is True
        assert uow.contacts.get(other).refresh_email is False


def test_several_people_are_looked_up_a_few_names_per_search() -> None:
    from outbound.stages.research.linkedin import find_linkedin_many

    names = ["Ann Ames", "Bob Bell", "Cy Cole", "Dee Dunn", "Eve Ens", "Fay Ford", "Gus Gale"]
    hits = [
        SearchHit(url="https://www.linkedin.com/in/p0", title="Ann Ames - CTO - Acme"),
        SearchHit(url="https://www.linkedin.com/in/p6", title="Gus Gale - CEO - Acme"),
        SearchHit(url="https://www.linkedin.com/in/x", title="Dee Dunn - CTO - Rival Ltd"),
    ]
    search = FakeSearch({}, hits)
    found = find_linkedin_many(search, names, "Acme", "acme.com")
    assert len(search.searches) == 2  # seven people, five names a search
    assert found == {
        "Ann Ames": "https://www.linkedin.com/in/p0",
        "Gus Gale": "https://www.linkedin.com/in/p6",
    }  # Dee Dunn's namesake works at another company
