"""Stages 7 and 8: the review actions, and delivery with its second safety check."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from outbound.db.models import EventRow
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.entities import Company, Message
from outbound.domain.enums import (
    CompanySource,
    CompanyStatus,
    ContactSource,
    ContactStatus,
    EmailStatus,
    EntityType,
    HoldReason,
    MessageState,
    Provenance,
    SuppressionKind,
    SuppressionReason,
)
from outbound.domain.policy_seeds import DEFAULT_COUNTRY_POLICIES
from outbound.providers.errors import ProviderError
from outbound.providers.ports import OutgoingDraft
from outbound.runner.guards import Guards
from outbound.runner.runner import Outcome, Runner
from outbound.services.review import ReviewError, ReviewService, footer_of
from outbound.stages.deliver import DeliverStage, draft_message_id
from tests.stages.fakes import REVISED_EMAIL, FakeLlm

C = CompanyStatus
FOOTER = 'Quantra Inc, 1 Main St. Reply "unsubscribe" and we will stop.'
BODY = f"Hi Jane,\n\nI saw the Leeds office. Would a call help?\n\nSam Lee\n\n--\n{FOOTER}"


class FakeMailbox:
    address = "sam@quantra.example"

    def __init__(self, *, fail_once: bool = False) -> None:
        self.drafts: dict[str, OutgoingDraft] = {}
        self.appends = 0
        self._fail_once = fail_once

    def append_draft(self, draft: OutgoingDraft) -> str:
        self.appends += 1
        if self._fail_once:
            self._fail_once = False
            raise ProviderError("imap", "connection reset", retryable=True)
        assert draft.message_id
        self.drafts[draft.message_id] = draft
        return draft.message_id

    def draft_exists(self, remote_draft_id: str) -> bool:
        return remote_draft_id in self.drafts

    def delete_draft(self, remote_draft_id: str) -> int:
        return int(self.drafts.pop(remote_draft_id, None) is not None)

    def list_sent(self, since: Any) -> list[Any]:
        return []

    def list_inbox(self, since: Any) -> list[Any]:
        return []


def copy_ready(
    factory: UnitOfWorkFactory,
    ws: str,
    *,
    domain: str = "acme.com",
    country: str = "US",
    provenance: Provenance = Provenance.API_DATABASE,
) -> tuple[str, str]:
    """A company at ``copy_ready`` with a generated message. Returns (company id, message id)."""
    with factory(ws) as uow:
        for policy in DEFAULT_COUNTRY_POLICIES:
            uow.policies.add_if_missing(policy)
        company = uow.companies.create(
            domain=domain, source=CompanySource.MANUAL, country_code=country, name="Acme"
        )
        version = company.row_version
        for step in (C.RESEARCHED, C.QUALIFIED, C.CONTACTS_FOUND, C.EMAIL_READY, C.COPY_READY):
            version = uow.companies.transition(
                company.id, step, expected_version=version
            ).row_version
        contact = uow.contacts.add(
            company.id,
            rank=1,
            source=ContactSource.SITE,
            full_name="Jane Doe",
            first_name="Jane",
            status=ContactStatus.ACTIVE,
        )
        address = uow.emails.add(
            contact.id,
            f"jane@{domain}",
            provenance,
            status=EmailStatus.VALID,
            is_primary=True,
        )
        message = uow.messages.create(
            company_id=company.id,
            contact_id=contact.id,
            contact_email_id=address.id,
            step=0,
            subject="leeds solar forecasts",
            generated_body=BODY,
            lint_report={"flagged": False},
        )
        uow.commit()
        return company.id, message.id


def review(factory: UnitOfWorkFactory, ws: str) -> ReviewService:
    return ReviewService(factory, ws)


def company(factory: UnitOfWorkFactory, ws: str, company_id: str) -> Company:
    with factory(ws) as uow:
        return uow.companies.get(company_id)


def message(factory: UnitOfWorkFactory, ws: str, message_id: str) -> Message:
    with factory(ws) as uow:
        return uow.messages.get(message_id)


# ------------------------------------------------------------------ review


def test_the_queue_lists_generated_messages_with_their_lint_flag(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    copy_ready(factory, ws)
    [item] = review(factory, ws).queue()
    assert (item.company.domain, item.contact.full_name, item.address.email) == (
        "acme.com",
        "Jane Doe",
        "jane@acme.com",
    )
    assert item.flagged is False


def test_approving_without_edits_moves_message_and_company(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid, mid = copy_ready(factory, ws)
    review(factory, ws).approve(mid)
    assert message(factory, ws, mid).state is MessageState.APPROVED
    assert message(factory, ws, mid).final_body is None
    assert company(factory, ws, cid).status is C.APPROVED
    assert review(factory, ws).queue() == []


def test_an_edit_is_stored_beside_the_original_with_its_distance_and_an_event(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    _cid, mid = copy_ready(factory, ws)
    edited = BODY.replace("I saw the Leeds office.", "Congrats on the Leeds office!")
    review(factory, ws).approve(mid, edited_body=edited)
    saved = message(factory, ws, mid)
    assert saved.generated_body == BODY
    assert saved.final_body == edited
    assert saved.edit_distance is not None and 0 < saved.edit_distance < 0.5
    with factory(ws) as uow:
        types = [e.type for e in uow.session.scalars(select(EventRow))]
    assert "edited" in types


def test_an_edit_identical_to_the_original_is_not_an_edit(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    _, mid = copy_ready(factory, ws)
    review(factory, ws).approve(mid, edited_body=BODY + "\n")
    assert message(factory, ws, mid).final_body is None


def test_an_edit_that_removes_the_footer_is_refused(factory: UnitOfWorkFactory, ws: str) -> None:
    cid, mid = copy_ready(factory, ws)
    with pytest.raises(ReviewError, match="footer"):
        review(factory, ws).approve(mid, edited_body="Hi Jane, just a short note. Call?")
    assert message(factory, ws, mid).state is MessageState.GENERATED
    assert company(factory, ws, cid).status is C.COPY_READY


def test_rejecting_needs_a_reason_and_ends_the_lead(factory: UnitOfWorkFactory, ws: str) -> None:
    cid, mid = copy_ready(factory, ws)
    with pytest.raises(ReviewError, match="why"):
        review(factory, ws).reject(mid, "  ")
    review(factory, ws).reject(mid, "wrong person")
    assert message(factory, ws, mid).state is MessageState.REJECTED
    assert company(factory, ws, cid).status is C.REJECTED
    with factory(ws) as uow:
        events = uow.events.for_entity(EntityType.MESSAGE, mid)
    assert any(e.type == "rejected" and e.data["reason"] == "wrong person" for e in events)


def test_a_message_can_only_be_reviewed_once(factory: UnitOfWorkFactory, ws: str) -> None:
    _, mid = copy_ready(factory, ws)
    review(factory, ws).approve(mid)
    with pytest.raises(ReviewError, match="not waiting"):
        review(factory, ws).approve(mid)
    with pytest.raises(ReviewError, match="not waiting"):
        review(factory, ws).reject(mid, "late")


def test_an_unknown_message_is_a_clear_error(factory: UnitOfWorkFactory, ws: str) -> None:
    with pytest.raises(ReviewError, match="no message"):
        review(factory, ws).approve("nope")


def test_a_short_prefix_finds_the_message_and_an_ambiguous_one_is_refused(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    _, mid = copy_ready(factory, ws)
    copy_ready(factory, ws, domain="beta.com")
    assert review(factory, ws).resolve(mid[:20]) == mid
    with pytest.raises(ReviewError, match="matches 2"):
        review(factory, ws).resolve(mid[:4])
    with pytest.raises(ReviewError, match="no message"):
        review(factory, ws).resolve("zzzz")


def test_show_gives_the_email_next_to_the_operator_notes(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid, mid = copy_ready(factory, ws)
    with factory(ws) as uow:
        from outbound.domain.enums import NoteSource

        uow.notes.add(cid, "met at the expo", NoteSource.OPERATOR)
        uow.commit()
    detail = review(factory, ws).show(mid)
    assert detail.notes == ["met at the expo"]
    assert detail.item.message.generated_body == BODY


def test_the_footer_is_found_after_the_dashes() -> None:
    assert footer_of(BODY) == FOOTER
    assert footer_of("no footer here") is None


# ------------------------------------------------------------------ deliver


def approved(factory: UnitOfWorkFactory, ws: str, **kwargs: Any) -> tuple[str, str]:
    cid, mid = copy_ready(factory, ws, **kwargs)
    review(factory, ws).approve(mid)
    return cid, mid


def deliver(factory: UnitOfWorkFactory, ws: str, mailbox: FakeMailbox) -> Any:
    return Runner(factory, ws, [DeliverStage(mailbox)], Guards()).run_pipeline()


def test_an_approved_email_becomes_a_mailbox_draft_and_the_lead_goes_in_sequence(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid, mid = approved(factory, ws)
    box = FakeMailbox()
    report = deliver(factory, ws, box)
    assert report.count("deliver", Outcome.ADVANCED) == 1
    saved = message(factory, ws, mid)
    assert saved.state is MessageState.DRAFTED
    assert saved.remote_draft_id == draft_message_id(saved, box.address)
    assert company(factory, ws, cid).status is C.IN_SEQUENCE
    [draft] = box.drafts.values()
    assert (draft.to_address, draft.subject, draft.body) == (
        "jane@acme.com",
        "leeds solar forecasts",
        BODY,
    )


def test_the_edited_text_is_what_gets_drafted(factory: UnitOfWorkFactory, ws: str) -> None:
    _cid, mid = copy_ready(factory, ws)
    edited = BODY.replace("Would a call help?", "Free for a quick call?")
    review(factory, ws).approve(mid, edited_body=edited)
    box = FakeMailbox()
    deliver(factory, ws, box)
    assert next(iter(box.drafts.values())).body == edited


def test_a_crash_after_saving_but_before_recording_does_not_duplicate_the_draft(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    _cid, mid = approved(factory, ws)
    box = FakeMailbox()
    saved = message(factory, ws, mid)
    # The previous attempt saved the draft, then died before the database was updated.
    box.drafts[draft_message_id(saved, box.address)] = OutgoingDraft(
        to_address="jane@acme.com", subject="s", body="b"
    )
    deliver(factory, ws, box)
    assert box.appends == 0
    assert message(factory, ws, mid).state is MessageState.DRAFTED


def test_a_mailbox_failure_leaves_the_lead_approved_and_a_rerun_finishes(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid, mid = approved(factory, ws)
    box = FakeMailbox(fail_once=True)
    report = deliver(factory, ws, box)
    assert report.count("deliver", Outcome.DEFERRED) == 1
    assert company(factory, ws, cid).status is C.APPROVED
    assert message(factory, ws, mid).state is MessageState.APPROVED
    with factory(ws) as uow:
        uow.companies.update_fields(
            cid,
            {"next_action_at": None},
            actor="system",
            expected_version=uow.companies.get(cid).row_version,
        )
        uow.commit()
    deliver(factory, ws, box)
    assert company(factory, ws, cid).status is C.IN_SEQUENCE
    assert len(box.drafts) == 1


def test_a_suppression_added_after_approval_stops_the_draft(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    _cid, mid = approved(factory, ws)
    with factory(ws) as uow:
        uow.suppressions.add(SuppressionKind.EMAIL, "jane@acme.com", SuppressionReason.OPT_OUT)
        uow.commit()
    box = FakeMailbox()
    report = deliver(factory, ws, box)
    assert box.appends == 0
    assert report.count("deliver", Outcome.HELD) == 1
    held = company(factory, ws, _cid)
    assert (held.status, held.hold_reason) == (C.HELD, HoldReason.NEEDS_OPERATOR)
    assert message(factory, ws, mid).state is MessageState.CANCELLED  # the approval is withdrawn


def test_a_domain_suppressed_after_approval_ends_the_lead_without_a_draft(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid, _ = approved(factory, ws)
    with factory(ws) as uow:
        uow.suppressions.add(SuppressionKind.DOMAIN, "acme.com", SuppressionReason.OPT_OUT)
        uow.commit()
    box = FakeMailbox()
    deliver(factory, ws, box)
    assert box.appends == 0
    assert company(factory, ws, cid).status is C.SUPPRESSED


def test_a_policy_changed_to_block_between_approval_and_delivery_never_drafts(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid, mid = approved(factory, ws)
    with factory(ws) as uow:
        from sqlalchemy import text

        uow.session.execute(
            text("UPDATE country_policies SET rule = 'block' WHERE country_code = 'US'")
        )
        uow.commit()
    box = FakeMailbox()
    deliver(factory, ws, box)
    assert box.appends == 0
    # Held, not suppressed, and the approval is withdrawn: once released it gets a fresh email.
    assert company(factory, ws, cid).status is C.HELD
    assert message(factory, ws, mid).state is MessageState.CANCELLED


def test_a_policy_that_now_needs_consent_for_this_address_never_drafts(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid, mid = approved(factory, ws, country="CA", provenance=Provenance.PATTERN_INFERRED)
    box = FakeMailbox()
    report = deliver(factory, ws, box)
    assert box.appends == 0
    assert report.count("deliver", Outcome.HELD) == 1
    held = company(factory, ws, cid)
    assert (held.status, held.hold_reason) == (C.HELD, HoldReason.CONSENT_REQUIRED)
    assert message(factory, ws, mid).state is MessageState.CANCELLED


def test_a_contact_who_opted_out_after_approval_blocks_the_draft(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid, _mid = approved(factory, ws)
    with factory(ws) as uow:
        contact = uow.contacts.for_company(cid)[0]
        uow.contacts.transition(contact.id, ContactStatus.OPTED_OUT)
        uow.commit()
    box = FakeMailbox()
    deliver(factory, ws, box)
    assert box.appends == 0


def test_an_address_that_turned_out_invalid_blocks_the_draft(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid, _mid = approved(factory, ws)
    with factory(ws) as uow:
        contact = uow.contacts.for_company(cid)[0]
        address = uow.emails.for_contact(contact.id)[0]
        uow.emails.transition(address.id, EmailStatus.INVALID)  # a bounce proved it bad
        uow.commit()
    box = FakeMailbox()
    deliver(factory, ws, box)
    assert box.appends == 0


# ------------------------------------------------------------------ revisions asked for on Review


def writer_review(
    factory: UnitOfWorkFactory, ws: str, llm: Any = None
) -> tuple[ReviewService, Any]:
    llm = llm or FakeLlm()
    return ReviewService(factory, ws, llm), llm


def test_an_email_is_revised_as_asked_with_the_footer_kept_and_nothing_saved(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    _, mid = copy_ready(factory, ws)
    service, llm = writer_review(factory, ws)
    edited = BODY.replace("Would a call help?", "Could we talk?")
    revision = service.revise(mid, "Warmer, and say we work with UK traders.", current=edited)
    assert revision.body == f"{REVISED_EMAIL}\n\n--\n{FOOTER}"
    prompt = llm.users["revise"]
    assert "Warmer, and say we work with UK traders." in prompt
    assert "Could we talk?" in prompt  # the operator's edits are what gets revised
    assert FOOTER not in prompt  # the legal footer is never handed to the model
    assert revision.report.word_count > 0
    assert message(factory, ws, mid).state is MessageState.GENERATED  # nothing approved
    assert message(factory, ws, mid).final_body is None  # nothing saved
    with factory(ws) as uow:
        events = [
            e
            for e in uow.events.for_entities([(EntityType.MESSAGE, mid)])
            if e.type == "revision_asked"
        ]
    assert [e.data for e in events] == [
        {"instructions": "Warmer, and say we work with UK traders."}
    ]


def test_the_revision_is_approved_like_an_edit(factory: UnitOfWorkFactory, ws: str) -> None:
    _, mid = copy_ready(factory, ws)
    service, _ = writer_review(factory, ws)
    revised = service.revise(mid, "Shorter.").body
    approved = service.approve(mid, edited_body=revised)
    assert approved.final_body == revised
    assert approved.edit_distance is not None and approved.edit_distance > 0


def test_a_revision_needs_instructions_a_writer_and_a_waiting_email(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    _, mid = copy_ready(factory, ws)
    service, _ = writer_review(factory, ws)
    with pytest.raises(ReviewError, match="say what to change"):
        service.revise(mid, "   ")
    with pytest.raises(ReviewError, match="no writer model"):
        ReviewService(factory, ws).revise(mid, "Shorter.")
    service.approve(mid)
    with pytest.raises(ReviewError):
        service.revise(mid, "Shorter.")
