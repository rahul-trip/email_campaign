"""LinkedIn messages: written after people are found, pasted by hand, and holding the email."""

from __future__ import annotations

import pytest

from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import (
    CompanySource,
    CompanyStatus,
    ContactSource,
    ContactStatus,
    HoldReason,
    LinkedInState,
    MessageState,
    Provenance,
)
from outbound.domain.policy_seeds import DEFAULT_COUNTRY_POLICIES
from outbound.providers.errors import ProviderError
from outbound.runner.guards import Guards
from outbound.runner.runner import Runner
from outbound.services.leads import LeadError, LeadService
from outbound.services.linkedin import LinkedInService
from outbound.stages.contacts import ContactsStage
from tests.stages.fakes import FakeLlm
from tests.stages.world import PROFILE

C = CompanyStatus


def lead(factory: UnitOfWorkFactory, ws: str, *, reviewed: bool = True) -> str:
    """A qualified lead with a CTO who has a profile, an engineer, and someone unconfirmed."""
    with factory(ws) as uow:
        for policy in DEFAULT_COUNTRY_POLICIES:
            uow.policies.add_if_missing(policy)
        uow.own_workspace.set_sender_profile(PROFILE if reviewed else {})
        campaign = uow.campaigns.create("c", ["CTO"])
        company = uow.companies.create(
            domain="acme.com",
            source=CompanySource.MANUAL,
            name="Acme",
            country_code="US",
            campaign_id=campaign.id,
        )
        version = company.row_version
        for step in (C.RESEARCHED, C.QUALIFIED):
            version = uow.companies.transition(
                company.id, step, expected_version=version
            ).row_version
        people = [
            ("Jane Doe", "CTO", "janedoe", ContactStatus.CANDIDATE),
            ("Eve Ng", "Software Engineer", "evenng", ContactStatus.CANDIDATE),
            ("Sam Roe", "CTO", "samroe", ContactStatus.UNCONFIRMED),
            ("Ann Poe", "CEO", None, ContactStatus.CANDIDATE),  # no profile
        ]
        for rank, (name, title, slug, status) in enumerate(people, start=1):
            uow.contacts.add(
                company.id,
                rank=rank,
                source=ContactSource.SEARCH,
                full_name=name,
                title=title,
                linkedin_url=f"https://www.linkedin.com/in/{slug}" if slug else None,
                status=status,
            )
        uow.commit()
        return company.id


def run(factory: UnitOfWorkFactory, ws: str, llm: FakeLlm | None = None) -> FakeLlm:
    llm = llm or FakeLlm()
    Runner(factory, ws, [ContactsStage(llm)], Guards()).run_pipeline()
    return llm


def drafts(factory: UnitOfWorkFactory, ws: str, cid: str) -> dict[str, str]:
    with factory(ws) as uow:
        names = {c.id: c.full_name or "" for c in uow.contacts.for_company(cid)}
        return {names[m.contact_id]: m.state.value for m in uow.linkedin.for_company(cid)}


def test_drafts_are_written_for_confirmed_decision_makers_with_a_profile(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = lead(factory, ws)
    llm = run(factory, ws)
    # Jane is a CTO with a profile. Eve is not a decision-maker, Sam is unconfirmed and Ann has
    # no profile: none of them is written to.
    assert drafts(factory, ws, cid) == {"Jane Doe": "drafted"}
    assert llm.calls.count("linkedin") == 1
    with factory(ws) as uow:
        assert uow.companies.get(cid).status is C.CONTACTS_FOUND
        (draft,) = uow.linkedin.for_company(cid)
    assert len(draft.note) <= 200 and draft.issues == ()


def test_a_rerun_does_not_write_the_same_person_twice(factory: UnitOfWorkFactory, ws: str) -> None:
    cid = lead(factory, ws)
    run(factory, ws)
    with factory(ws) as uow:  # back to the contacts step, as research again would
        company = uow.companies.get(cid)
        uow.companies.transition(cid, C.NEW, expected_version=company.row_version)
        version = uow.companies.get(cid).row_version
        for step in (C.RESEARCHED, C.QUALIFIED):
            version = uow.companies.transition(cid, step, expected_version=version).row_version
        uow.commit()
    llm = run(factory, ws)
    assert llm.calls.count("linkedin") == 0
    assert len(drafts(factory, ws, cid)) == 1


def test_a_model_failure_never_fails_the_lead(factory: UnitOfWorkFactory, ws: str) -> None:
    class Down(FakeLlm):
        def complete(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise ProviderError("fake-llm", "down")

    cid = lead(factory, ws)
    run(factory, ws, Down())
    assert drafts(factory, ws, cid) == {}
    with factory(ws) as uow:
        assert uow.companies.get(cid).status is C.CONTACTS_FOUND


def test_nothing_is_written_until_the_sender_profile_is_reviewed(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = lead(factory, ws, reviewed=False)
    llm = run(factory, ws)
    assert drafts(factory, ws, cid) == {} and llm.calls.count("linkedin") == 0


def test_a_draft_that_breaks_a_rule_is_rewritten_once_then_kept_with_its_issues(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = lead(factory, ws)
    llm = FakeLlm({"linkedin": {"drafts": [{"n": 1, "note": "x" * 300, "message": "too short"}]}})
    run(factory, ws, llm)
    assert llm.calls.count("linkedin") == 2  # the draft and one rewrite
    with factory(ws) as uow:
        (draft,) = uow.linkedin.for_company(cid)
    assert draft.issues  # the operator sees what is still wrong


def service(factory: UnitOfWorkFactory, ws: str) -> LinkedInService:
    return LinkedInService(factory, ws, llm=FakeLlm())


def test_a_draft_can_be_written_on_request_edited_skipped_and_restored(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = lead(factory, ws)
    with factory(ws) as uow:
        eve = next(c for c in uow.contacts.for_company(cid) if c.full_name == "Eve Ng")
        sam = next(c for c in uow.contacts.for_company(cid) if c.full_name == "Sam Roe")
    svc = service(factory, ws)
    with pytest.raises(LeadError, match="confirm"):
        svc.write(sam.id)  # unconfirmed: not until they are confirmed to work here
    draft = svc.write(eve.id)  # the operator asks for an engineer by hand
    assert draft.state is LinkedInState.DRAFTED
    edited = svc.edit(draft.id, note="Hello Eve", message="My own words")
    assert (edited.edited, edited.issues) == (True, ())
    assert svc.skip(draft.id).state is LinkedInState.SKIPPED
    assert svc.restore(draft.id).state is LinkedInState.DRAFTED
    again = svc.write(eve.id)  # Rewrite replaces the text and the edit flag
    assert (again.id, again.edited) == (draft.id, False)


def waiting_email(factory: UnitOfWorkFactory, ws: str, cid: str, to: C) -> str:
    """Move the lead to ``to`` with a generated email to Jane, as the pipeline would."""
    with factory(ws) as uow:
        jane = next(c for c in uow.contacts.for_company(cid) if c.full_name == "Jane Doe")
        address = uow.emails.add(jane.id, "jane@acme.com", Provenance.API_DATABASE, is_primary=True)
        version = uow.companies.get(cid).row_version
        for step in (C.EMAIL_READY, C.COPY_READY):  # the lead is at CONTACTS_FOUND already
            version = uow.companies.transition(cid, step, expected_version=version).row_version
            if step is to:
                break
        message = uow.messages.create(
            company_id=cid,
            contact_id=jane.id,
            contact_email_id=address.id,
            step=0,
            subject="hello",
            generated_body="body",
        )
        uow.commit()
        return message.id


def test_marking_sent_holds_the_lead_and_cancels_the_waiting_email_and_release_resumes(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = lead(factory, ws)
    run(factory, ws)
    email_id = waiting_email(factory, ws, cid, C.COPY_READY)
    (draft,) = LinkedInService(factory, ws).for_company(cid)
    sent = service(factory, ws).mark_sent(draft.id)
    assert (sent.message.state, sent.email_held) == (LinkedInState.SENT, True)
    with factory(ws) as uow:
        company = uow.companies.get(cid)
        assert (company.status, company.hold_reason) == (C.HELD, HoldReason.LINKEDIN_CONTACTED)
        assert uow.messages.get(email_id).state is MessageState.CANCELLED
    with pytest.raises(LeadError, match="already"):
        service(factory, ws).mark_sent(draft.id)  # sent is final
    with pytest.raises(LeadError):
        service(factory, ws).skip(draft.id)
    released = LeadService(factory, ws).release_hold(cid)
    assert released.status is C.CONTACTS_FOUND  # the email step reruns from what it already found


def test_an_email_already_in_the_mailbox_is_left_alone(factory: UnitOfWorkFactory, ws: str) -> None:
    cid = lead(factory, ws)
    run(factory, ws)
    waiting_email(factory, ws, cid, C.COPY_READY)
    with factory(ws) as uow:
        version = uow.companies.get(cid).row_version
        uow.companies.transition(cid, C.APPROVED, expected_version=version)
        uow.commit()
    (draft,) = LinkedInService(factory, ws).for_company(cid)
    sent = service(factory, ws).mark_sent(draft.id)
    assert sent.email_held is False
    with factory(ws) as uow:
        assert uow.companies.get(cid).status is C.APPROVED


def test_forgetting_a_person_removes_their_linkedin_draft(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = lead(factory, ws)
    run(factory, ws)
    with factory(ws) as uow:
        jane = next(c for c in uow.contacts.for_company(cid) if c.full_name == "Jane Doe")
        uow.erasure.scrub_contact(jane.id, None)
        uow.commit()
        assert uow.linkedin.for_company(cid) == []


def test_the_page_lists_messages_by_state_with_who_they_are_for(
    factory: UnitOfWorkFactory, ws: str, other_ws: str
) -> None:
    cid = lead(factory, ws)
    run(factory, ws)
    rows, total = service(factory, ws).page(LinkedInState.DRAFTED)
    assert (total, rows[0].person, rows[0].domain) == (1, "Jane Doe", "acme.com")
    assert service(factory, ws).page(LinkedInState.SENT) == ([], 0)
    assert service(factory, other_ws).page(LinkedInState.DRAFTED) == ([], 0)  # not another's
    assert cid


def test_the_email_is_told_the_person_was_already_messaged_on_linkedin(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    from outbound.stages.copy.stage import _with_linkedin

    cid = lead(factory, ws)
    run(factory, ws)
    (draft,) = LinkedInService(factory, ws).for_company(cid)
    assert _with_linkedin("operator note", draft) == "operator note"  # not sent: nothing to say
    sent = service(factory, ws).mark_sent(draft.id).message
    told = _with_linkedin("operator note", sent)
    assert told.startswith("operator note\n") and "already messaged this person on LinkedIn" in told
    assert draft.note in told


def test_everyone_at_a_lead_is_drafted_in_one_call_and_only_failures_are_rewritten() -> None:
    from outbound.stages.linkedin import LinkedInLead, write_linkedin_many

    good = FakeLlm().replies["linkedin"]["drafts"][0]
    llm = FakeLlm(
        {
            "linkedin": {
                "drafts": [
                    {**good, "n": 1},
                    {**good, "n": 2, "note": "x" * 300},  # too long: rewritten
                    {**good, "n": 3},
                ]
            }
        }
    )
    lead = LinkedInLead(sender=PROFILE, company_name="Acme", research={})
    out = write_linkedin_many(llm, lead, [("Jane", "CTO"), ("Ann", "CEO"), ("Bo", "VP")])
    assert llm.calls.count("linkedin") == 2  # three people, one draft call and one rewrite
    assert "Recipient 2: your previous draft" in llm.users["linkedin"]
    assert "Recipient 1:" not in llm.users["linkedin"]  # the good ones are not asked again
    assert [d is not None and not d.issues for d in out] == [True, False, True]
