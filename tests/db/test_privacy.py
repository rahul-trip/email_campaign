"""Forget and suppress, proven through the real pipeline rather than hand-made rows."""

from __future__ import annotations

import pytest
from sqlalchemy import Engine

from outbound.bootstrap import container_for
from outbound.config import Settings
from outbound.db.errors import NotFound
from outbound.db.models import WorkspaceRow
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import (
    CompanyStatus,
    ContactStatus,
    MessageState,
    SuppressionKind,
    SuppressionReason,
)
from outbound.domain.errors import InvalidInput
from outbound.domain.policy_seeds import DEFAULT_COUNTRY_POLICIES
from outbound.pipeline import Pipeline, assemble
from outbound.providers.errors import ProviderError
from outbound.services.privacy import PrivacyService
from tests.db.test_forget import occurrences
from tests.stages.fakes import FakeMailbox
from tests.stages.world import PROFILE, World

ADDRESS = "jane.doe@acme.co.uk"
NAME = "Jane Doe"


class FailingMailbox(FakeMailbox):
    def delete_draft(self, remote_draft_id: str) -> int:
        raise ProviderError("imap", "connection reset", retryable=True)


def drafted_lead(
    engine: Engine, factory: UnitOfWorkFactory, ws: str, world: World, domain: str = "acme.co.uk"
) -> tuple[Pipeline, str]:
    """A lead taken all the way to a draft in the mailbox, by the real stages."""
    with factory(ws) as uow:
        for policy in DEFAULT_COUNTRY_POLICIES:
            uow.policies.add_if_missing(policy)
        row = uow.session.get(WorkspaceRow, ws)
        assert row is not None
        row.sender_profile = PROFILE
        if uow.campaigns.by_name("default") is None:
            uow.campaigns.create("default", ["CTO"], icp_description="Utilities")
        uow.commit()
    pipeline = assemble(container_for(Settings(_env_file=None), engine), ws, world.providers())
    pipeline.intake.run([{"Website": domain, "Company": "Acme Energy", "Country": "UK"}])
    pipeline.runner.run_pipeline()
    [queued] = pipeline.review.queue()
    pipeline.review.approve(queued.message.id)
    pipeline.runner.run_pipeline()
    assert len(world.mailbox.drafts) == 1
    return pipeline, queued.company.id


def privacy(factory: UnitOfWorkFactory, ws: str, world: World) -> PrivacyService:
    return PrivacyService(factory, ws, world.mailbox)


# ------------------------------------------------------------------ forget


def test_before_forgetting_the_person_is_in_the_real_data(
    engine: Engine, factory: UnitOfWorkFactory, ws: str
) -> None:
    """Guards the scan below: it must find the person where real runs put them."""
    drafted_lead(engine, factory, ws, World())
    assert "contact_emails.email" in occurrences(engine, ADDRESS)
    assert "messages.generated_body" in occurrences(engine, "Hi Jane")
    assert "provider_calls.response" in occurrences(engine, NAME)  # the team page and the reply
    assert "provider_calls.response" in occurrences(engine, ADDRESS)  # the finder's answer


def test_forgetting_a_person_after_a_real_run_leaves_no_trace_anywhere(
    engine: Engine, factory: UnitOfWorkFactory, ws: str
) -> None:
    world = World()
    drafted_lead(engine, factory, ws, world)

    result = privacy(factory, ws, world).forget(ADDRESS)

    assert result.found and result.messages_cancelled == 1
    assert (result.drafts_deleted, result.drafts_left) == (1, ())
    assert world.mailbox.drafts == {}  # the draft was removed from the mailbox too
    for needle in (ADDRESS, NAME, "jane.doe"):
        assert occurrences(engine, needle) == [], f"{needle!r}: {occurrences(engine, needle)}"


def test_a_mailbox_failure_never_undoes_the_erasure(
    engine: Engine, factory: UnitOfWorkFactory, ws: str
) -> None:
    world = World()
    world.mailbox = FailingMailbox()
    drafted_lead(engine, factory, ws, world)
    draft_ids = list(world.mailbox.drafts)

    result = privacy(factory, ws, world).forget(ADDRESS)

    assert result.found and result.drafts_deleted == 0
    assert list(result.drafts_left) == draft_ids  # told to the operator to remove by hand
    assert occurrences(engine, ADDRESS) == []


def test_forgetting_an_address_we_never_held_still_suppresses_it(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    result = PrivacyService(factory, ws).forget("stranger@elsewhere.com")
    assert not result.found
    with factory(ws) as uow:
        assert uow.suppressions.is_email_suppressed("stranger@elsewhere.com")


# ------------------------------------------------------------------ suppress


def test_suppressing_a_person_cancels_their_email_and_removes_the_draft(
    engine: Engine, factory: UnitOfWorkFactory, ws: str
) -> None:
    world = World()
    _, company_id = drafted_lead(engine, factory, ws, world)
    with factory(ws) as uow:
        [contact] = uow.contacts.for_company(company_id)

    result = privacy(factory, ws, world).suppress_contact(contact.id)

    assert (result.messages_cancelled, result.drafts_deleted) == (1, 1)
    assert world.mailbox.drafts == {}
    with factory(ws) as uow:
        assert uow.contacts.get(contact.id).status is ContactStatus.OPTED_OUT
        assert uow.companies.get(company_id).status is CompanyStatus.SUPPRESSED
        assert uow.suppressions.is_email_suppressed(ADDRESS)
        assert [m.state for m in uow.messages.for_company(company_id)] == [MessageState.CANCELLED]
        assert (
            uow.contacts.get(contact.id).full_name == NAME
        )  # kept: this is an opt-out, not erasure


def test_suppressing_a_company_blocks_its_whole_domain(
    engine: Engine, factory: UnitOfWorkFactory, ws: str
) -> None:
    world = World()
    _, company_id = drafted_lead(engine, factory, ws, world)

    result = privacy(factory, ws, world).suppress_company(company_id)

    assert result.drafts_deleted == 1 and world.mailbox.drafts == {}
    with factory(ws) as uow:
        assert uow.companies.get(company_id).status is CompanyStatus.SUPPRESSED
        assert uow.suppressions.is_domain_suppressed("acme.co.uk")


def test_a_suppressed_address_is_never_chosen_again_by_a_new_lead(
    engine: Engine, factory: UnitOfWorkFactory, ws: str
) -> None:
    drafted_lead(engine, factory, ws, World())
    PrivacyService(factory, ws).suppress_value("acme.co.uk")
    pipeline = assemble(container_for(Settings(_env_file=None), engine), ws, World().providers())
    report = pipeline.intake.run([{"Website": "www.acme.co.uk"}])
    assert report.rows[0].status.value in {"merged", "rejected"}


@pytest.mark.parametrize(
    ("value", "kind"),
    [("nobody@unknown.com", SuppressionKind.EMAIL), ("unknown.com", SuppressionKind.DOMAIN)],
)
def test_suppressing_something_we_do_not_hold_still_records_it(
    factory: UnitOfWorkFactory, ws: str, value: str, kind: SuppressionKind
) -> None:
    result = PrivacyService(factory, ws).suppress_value(value)
    assert not result.found
    with factory(ws) as uow:
        assert uow.suppressions.add(kind, value, SuppressionReason.MANUAL) is False  # already there


def test_an_empty_value_is_refused(factory: UnitOfWorkFactory, ws: str) -> None:
    with pytest.raises(InvalidInput):
        PrivacyService(factory, ws).suppress_value("  ")


def test_another_workspaces_people_and_companies_cannot_be_touched(
    engine: Engine, factory: UnitOfWorkFactory, ws: str, other_ws: str
) -> None:
    world = World()
    _, company_id = drafted_lead(engine, factory, ws, world)
    with factory(ws) as uow:
        [contact] = uow.contacts.for_company(company_id)
    intruder = PrivacyService(factory, other_ws, world.mailbox)
    with pytest.raises(NotFound):
        intruder.suppress_contact(contact.id)
    with pytest.raises(NotFound):
        intruder.suppress_company(company_id)
    assert len(world.mailbox.drafts) == 1
