"""Deleting a lead removes it for good, only when that is safe, and never touches another lead."""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, func, select

from outbound.db.errors import NotFound
from outbound.db.models import ProviderCallRow
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import (
    CompanySource,
    CompanyStatus,
    ContactSource,
    EntityType,
    MessageState,
    Provenance,
)
from outbound.domain.errors import InvalidInput
from outbound.services.leads import LeadError
from outbound.services.privacy import PrivacyService
from outbound.stages.base import StageContext, StageResult
from tests.db.test_forget import NAME, PERSON, occurrences, populate
from tests.db.test_runner import FakeStage, add_company, make_runner
from tests.stages.fakes import FakeMailbox

C = CompanyStatus


def lead(
    factory: UnitOfWorkFactory, ws: str, mailbox: FakeMailbox | None = None
) -> tuple[PrivacyService, dict[str, str]]:
    with factory(ws) as uow:
        ids = populate(uow, ws)
        other = uow.companies.create(domain="beta.io", source=CompanySource.MANUAL, name="Beta")
        keeper = uow.contacts.add(
            other.id, rank=1, source=ContactSource.SITE, full_name="Kim Lee", first_name="Kim"
        )
        uow.emails.add(keeper.id, "kim@beta.io", Provenance.API_DATABASE, is_primary=True)
        uow.commit()
    ids["other"] = other.id
    return PrivacyService(factory, ws, mailbox), ids


def test_before_deleting_the_data_really_is_in_many_places(
    owner_engine: Engine, factory: UnitOfWorkFactory, engine: Engine, ws: str
) -> None:
    """Guards the scan below: if this found little, a clean scan would prove nothing."""
    _, ids = lead(factory, ws)
    assert {"contact_emails.email", "messages.generated_body", "notes.body"} <= set(
        occurrences(owner_engine, PERSON)
        + occurrences(owner_engine, "sailing")
        + occurrences(owner_engine, NAME)
    )
    assert len(occurrences(owner_engine, ids["company"])) >= 6


def test_deleting_removes_the_lead_and_every_trace_of_its_people(
    owner_engine: Engine, factory: UnitOfWorkFactory, engine: Engine, ws: str
) -> None:
    service, ids = lead(factory, ws)
    result = service.delete_lead(ids["company"], confirm_domain=" ACME.com ")
    assert (result.domain, result.contacts_removed, result.messages_removed) == ("acme.com", 2, 3)
    for needle in (PERSON, NAME, "sam@acme.com", "Sam Roe", "forecast error at acme", "sailing"):
        assert occurrences(owner_engine, needle) == [], (
            f"{needle!r}: {occurrences(owner_engine, needle)}"
        )
    # Nothing points at the lead any more except the one record that it was deleted.
    assert set(occurrences(owner_engine, ids["company"])) == {"events.entity_id"}
    with factory(ws) as uow:
        assert uow.companies.by_domain("acme.com") is None


def test_one_record_stays_that_it_happened_and_it_holds_no_personal_detail(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    service, ids = lead(factory, ws)
    service.delete_lead(ids["company"], confirm_domain="acme.com", actor="user:sam")
    with factory(ws) as uow:
        events = uow.events.for_entity(EntityType.COMPANY, ids["company"])
    assert [e.type for e in events] == ["lead_deleted"]
    assert events[0].actor == "user:sam"
    assert events[0].data == {
        "domain": "acme.com",
        "status_was": "new",
        "contacts": 2,
        "messages": 3,
        "domain_suppressed": False,
    }


def test_the_cost_ledger_keeps_its_rows_but_loses_the_link_and_the_vendor_answer(
    owner_engine: Engine, factory: UnitOfWorkFactory, engine: Engine, ws: str
) -> None:
    service, ids = lead(factory, ws)
    with owner_engine.connect() as connection:
        before = connection.scalar(select(func.sum(ProviderCallRow.cost_micro_usd)))
    service.delete_lead(ids["company"], confirm_domain="acme.com")
    with owner_engine.connect() as connection:
        assert connection.scalar(select(func.sum(ProviderCallRow.cost_micro_usd))) == before
        row = connection.execute(select(ProviderCallRow)).one()
    assert (row.company_id, row.contact_id, row.response) == (None, None, None)


def test_another_lead_is_left_exactly_as_it_was(
    owner_engine: Engine, factory: UnitOfWorkFactory, engine: Engine, ws: str
) -> None:
    service, ids = lead(factory, ws)
    service.delete_lead(ids["company"], confirm_domain="acme.com")
    with factory(ws) as uow:
        [kim] = uow.contacts.for_company(ids["other"])
        assert kim.full_name == "Kim Lee"
        assert [e.email for e in uow.emails.for_contact(kim.id)] == ["kim@beta.io"]
        assert uow.companies.get(ids["other"]).name == "Beta"
    assert occurrences(owner_engine, "kim@beta.io") != []


def test_a_wrong_confirmation_deletes_nothing(factory: UnitOfWorkFactory, ws: str) -> None:
    service, ids = lead(factory, ws)
    for typed in ("", "acme", "beta.io", "acme.com.au"):
        with pytest.raises(InvalidInput, match=r"acme\.com"):
            service.delete_lead(ids["company"], confirm_domain=typed)
    with factory(ws) as uow:
        assert uow.companies.get(ids["company"]).domain == "acme.com"
        assert len(uow.contacts.for_company(ids["company"])) == 2


def test_a_lead_we_have_emailed_cannot_be_deleted(factory: UnitOfWorkFactory, ws: str) -> None:
    service, ids = lead(factory, ws)
    with factory(ws) as uow:
        sent = uow.messages.transition(
            ids["drafted"],
            MessageState.SENT,
            expected_version=uow.messages.get(ids["drafted"]).row_version,
        )
        assert sent.state is MessageState.SENT
        uow.commit()
    with pytest.raises(LeadError, match="Suppress"):
        service.delete_lead(ids["company"], confirm_domain="acme.com")
    with factory(ws) as uow:
        assert uow.companies.get(ids["company"]).domain == "acme.com"  # still there


def test_drafts_waiting_in_the_mailbox_are_deleted_with_the_lead(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    mailbox = FakeMailbox()
    mailbox.drafts["draft-1"] = object()
    service, ids = lead(factory, ws, mailbox)
    result = service.delete_lead(ids["company"], confirm_domain="acme.com")
    assert (result.drafts_deleted, result.drafts_left) == (1, ())
    assert mailbox.drafts == {}


def test_a_draft_that_cannot_be_deleted_is_reported_not_lost(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    service, ids = lead(factory, ws, mailbox=None)  # no mailbox login configured
    result = service.delete_lead(ids["company"], confirm_domain="acme.com")
    assert result.drafts_left == ("draft-1",)
    with factory(ws) as uow:
        assert uow.companies.by_domain("acme.com") is None  # the database change still stands


def test_the_domain_can_be_blocked_from_ever_coming_back_or_left_open(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    service, ids = lead(factory, ws)
    service.delete_lead(ids["company"], confirm_domain="acme.com")
    with factory(ws) as uow:  # not blocked: it can simply be added again
        again = uow.companies.create(domain="acme.com", source=CompanySource.MANUAL)
        assert again.id != ids["company"]
        assert not uow.suppressions.blocks("someone@acme.com")
        uow.commit()
    service.delete_lead(again.id, confirm_domain="acme.com", also_suppress_domain=True)
    with factory(ws) as uow:
        assert uow.suppressions.blocks("someone@acme.com")


def test_another_workspaces_lead_is_not_found(
    factory: UnitOfWorkFactory, ws: str, other_ws: str
) -> None:
    _, ids = lead(factory, other_ws)
    with pytest.raises(NotFound):
        PrivacyService(factory, ws).delete_lead(ids["company"], confirm_domain="acme.com")


def test_a_lead_deleted_while_a_run_is_working_on_it_does_not_break_the_run(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    gone = add_company(factory, ws, "gone.com")
    kept = add_company(factory, ws, "kept.com")

    def delete_it(ctx: StageContext) -> StageResult | None:
        if ctx.company.domain == "gone.com":  # the operator deletes it mid-stage
            PrivacyService(factory, ws).delete_lead(gone, confirm_domain="gone.com")
        return None

    stage = FakeStage("research", C.NEW, C.RESEARCHED, action=delete_it)
    report = make_runner(factory, ws, [stage]).run_pipeline()
    assert report.status.value == "succeeded"
    with factory(ws) as uow:
        assert uow.companies.by_domain("gone.com") is None
        assert uow.companies.get(kept).status is C.RESEARCHED
