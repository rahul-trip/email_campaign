"""Find more people at a lead by role (recruiters, a head of engineering), and do what the person
chose for them: nothing, find their email, write a LinkedIn message, or both."""

from __future__ import annotations

from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import CompanyStatus, ContactStatus, LinkedInState
from outbound.providers.ports import SearchHit
from outbound.services.leads import LeadService
from outbound.services.linkedin import LinkedInService
from outbound.services.people import PeopleSearch, Reach
from tests.db.test_person_actions import hit, lead
from tests.stages.fakes import FakeLlm, FakeSearch
from tests.stages.world import PROFILE

C = CompanyStatus
RITA = hit(
    "https://www.linkedin.com/in/rita-hunt", "Rita Hunt - Technical Recruiter - Acme | LinkedIn"
)
TOM = hit("https://www.linkedin.com/in/tom-vale", "Tom Vale - Head of Talent - Acme | LinkedIn")


def company_of(factory: UnitOfWorkFactory, ws: str, person: str) -> str:
    with factory(ws) as uow:
        return uow.contacts.get(person).company_id


def finder(
    factory: UnitOfWorkFactory, ws: str, hits: list[SearchHit], llm: FakeLlm | None = None
) -> tuple[PeopleSearch, FakeSearch]:
    with factory(ws) as uow:
        uow.own_workspace.set_sender_profile(PROFILE)
        uow.commit()
    search = FakeSearch(hits=hits)
    llm = llm or FakeLlm()
    leads = LeadService(factory, ws, search=search, llm=llm)
    return PeopleSearch(leads, LinkedInService(factory, ws, llm=llm)), search


def test_the_roles_asked_for_are_searched_and_a_failed_lead_is_left_alone(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = company_of(factory, ws, lead(factory, ws, status=C.FAILED))
    people, search = finder(factory, ws, [RITA, TOM])
    result = people.find(cid, ["Recruiter", "Head of Talent"], Reach.NONE)
    assert '"Recruiter"' in search.searches[0] and '"Head of Talent"' in search.searches[0]
    assert (result.added, result.retried, result.error) == (2, False, "")
    assert [p.name for p in result.people] == ["Rita Hunt", "Tom Vale"]
    assert all(p.confirmed and p.email == "" and p.linkedin == "" for p in result.people)
    with factory(ws) as uow:  # whoever decides was not the point: the lead stays as it was
        assert uow.companies.get(cid).status is C.FAILED
        assert uow.linkedin.for_company(cid) == []


def test_email_and_linkedin_are_done_for_each_person_found_when_asked(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = company_of(factory, ws, lead(factory, ws, status=C.FAILED))
    people, _ = finder(factory, ws, [RITA])
    (rita,) = people.find(cid, ["Recruiter"], Reach.BOTH).people
    assert (rita.email, rita.linkedin) == ("asked", "written")
    with factory(ws) as uow:
        message = uow.linkedin.for_contact(rita.contact_id)
        assert message is not None and message.state is LinkedInState.DRAFTED
        assert uow.companies.get(cid).status is C.CONTACTS_FOUND  # the email step looks again
        assert uow.contacts.get(rita.contact_id).refresh_email is True


def test_the_person_can_choose_only_one_of_the_two(factory: UnitOfWorkFactory, ws: str) -> None:
    cid = company_of(factory, ws, lead(factory, ws, status=C.CONTACTS_FOUND))
    people, _ = finder(factory, ws, [RITA])
    (rita,) = people.find(cid, ["Recruiter"], Reach.LINKEDIN).people
    assert (rita.email, rita.linkedin) == ("", "written")
    with factory(ws) as uow:
        assert uow.contacts.get(rita.contact_id).refresh_email is False


def test_someone_not_placed_at_the_company_waits_for_a_person_to_confirm(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = company_of(factory, ws, lead(factory, ws))
    unsure = hit("https://www.linkedin.com/in/uma-park", "Uma Park - Recruiter | LinkedIn")
    people, _ = finder(factory, ws, [unsure])
    (uma,) = people.find(cid, ["Recruiter"], Reach.BOTH).people
    assert not uma.confirmed
    assert uma.email == uma.linkedin == "confirm they work here first"
    with factory(ws) as uow:
        assert uow.contacts.get(uma.contact_id).status is ContactStatus.UNCONFIRMED
        assert uow.linkedin.for_company(cid) == []  # nobody is written to before they are confirmed


def test_several_leads_are_searched_together_and_one_failing_does_not_stop_the_rest(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    first = company_of(factory, ws, lead(factory, ws, domain="acme.com"))
    second = company_of(factory, ws, lead(factory, ws, domain="bolt.com"))
    people, _ = finder(factory, ws, [RITA])
    results = people.find_many([first, "not-a-lead", second], ["Recruiter"], Reach.NONE)
    assert [r.company_id for r in results] == [first, "not-a-lead", second]
    assert results[1].error and results[1].added == 0
    assert results[0].error == "" and results[2].error == ""
    assert results[0].found == 1 and results[2].found == 1  # who is added first is not fixed
    assert results[0].added + results[2].added >= 1
