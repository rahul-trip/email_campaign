"""Phase 4a: an opt-out reply and a hard bounce each stop the person, on a fixture mailbox."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import (
    CompanyStatus,
    ContactSource,
    ContactStatus,
    EmailStatus,
    InboundCategory,
    MessageState,
    Provenance,
)
from outbound.providers.ports import InboundMessage
from outbound.services.inbox import InboxSync
from outbound.services.privacy import PrivacyService
from outbound.stages.mailboxes import one
from tests.db.test_sent_sync import drafted


class Inbox:
    address = "sam@quantra.example"

    def __init__(self) -> None:
        self.mail: list[InboundMessage] = []
        self.deleted: list[str] = []

    def list_inbox(self, since: datetime) -> list[InboundMessage]:
        return [m for m in self.mail if m.received_at >= since]

    def list_sent(self, since: datetime) -> list[Any]:
        return []

    def append_draft(self, draft: Any) -> str:
        raise AssertionError("never writes drafts")

    def draft_exists(self, remote_draft_id: str) -> bool:
        return True

    def delete_draft(self, remote_draft_id: str) -> int:
        self.deleted.append(remote_draft_id)
        return 1


def mail(ident: str, sender: str, subject: str, body: str, **extra: Any) -> InboundMessage:
    return InboundMessage(
        rfc_message_id=ident,
        from_address=sender,
        subject=subject,
        received_at=datetime.now(UTC) + timedelta(minutes=1),
        body=body,
        **extra,
    )


def setup(factory: UnitOfWorkFactory, ws: str) -> tuple[str, str, str, str, str]:
    """A sent touch 1, a drafted touch 2 to the same person, and a second person at the company.
    Returns (message id, rfc id, mailbox id, company id, contact email id)."""
    first = drafted(factory, ws)
    with factory(ws) as uow:
        sent = uow.messages.get(first)
        uow.messages.transition(
            first,
            MessageState.SENT,
            expected_version=sent.row_version,
            set_fields={"rfc_message_id": "<sent-1@q>", "sent_at": datetime.now(UTC)},
        )
        second = uow.messages.create(
            company_id=sent.company_id,
            contact_id=sent.contact_id,
            contact_email_id=sent.contact_email_id,
            step=1,
            subject="Re: leeds solar forecasts",
            generated_body="Following up.",
        )
        uow.messages.transition(
            second.id,
            MessageState.APPROVED,
            expected_version=second.row_version,
        )
        current = uow.messages.get(second.id)
        uow.messages.transition(
            second.id,
            MessageState.DRAFTED,
            expected_version=current.row_version,
            set_fields={"remote_draft_id": "<draft-2@q>"},
        )
        other = uow.contacts.add(
            sent.company_id, rank=2, source=ContactSource.SITE, full_name="K L"
        )
        uow.emails.add(other.id, "kim@acme.com", Provenance.API_DATABASE, status=EmailStatus.VALID)
        box = uow.mailboxes.create("sam@quantra.example", "quantra.example")
        uow.commit()
    return first, "<sent-1@q>", box.id, sent.company_id, sent.contact_email_id


def run(factory: UnitOfWorkFactory, ws: str, box_id: str, inbox: Inbox) -> dict[str, int]:
    mailboxes = one(inbox, box_id)
    privacy = PrivacyService(factory, ws, mailboxes)
    return InboxSync(factory, ws, mailboxes, privacy).run()


def test_an_unsubscribe_reply_suppresses_the_person_and_stops_their_emails(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    _first, rfc, box, company_id, address_id = setup(factory, ws)
    inbox = Inbox()
    inbox.mail = [
        mail(
            "<r1@x>",
            "jane@acme.com",
            "Re: leeds solar forecasts",
            "Please unsubscribe me.",
            in_reply_to=rfc,
            references=rfc,
        )
    ]
    counts = run(factory, ws, box, inbox)
    assert counts["unsubscribe"] == 1
    with factory(ws) as uow:
        address = uow.emails.get(address_id)
        assert uow.suppressions.is_email_suppressed("jane@acme.com")
        assert uow.contacts.get(address.contact_id).status is ContactStatus.OPTED_OUT
        states = {m.step: m.state for m in uow.messages.for_company(company_id)}
        assert states[1] is MessageState.CANCELLED
    assert inbox.deleted == ["<draft-2@q>"]
    # Reading the same mail again changes nothing.
    assert run(factory, ws, box, inbox)["unsubscribe"] == 0


def test_a_hard_bounce_invalidates_the_address_and_moves_the_lead_to_the_next_person(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    first, _rfc, box, company_id, address_id = setup(factory, ws)
    inbox = Inbox()
    inbox.mail = [
        mail(
            "<b1@x>",
            "MAILER-DAEMON@mail.example.org",
            "Undelivered Mail Returned to Sender",
            "Final-Recipient: rfc822; jane@acme.com\nStatus: 5.1.1\nuser unknown",
        )
    ]
    counts = run(factory, ws, box, inbox)
    assert counts["hard_bounce"] == 1
    with factory(ws) as uow:
        address = uow.emails.get(address_id)
        assert address.status is EmailStatus.INVALID
        assert uow.suppressions.is_email_suppressed("jane@acme.com")
        assert uow.contacts.get(address.contact_id).status is ContactStatus.BOUNCED
        assert uow.messages.get(first).state is MessageState.BOUNCED
        assert uow.companies.get(company_id).status is CompanyStatus.CONTACTS_FOUND
    assert inbox.deleted == ["<draft-2@q>"]


def test_mail_that_is_not_about_our_emails_is_ignored_and_not_kept(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    _first, _rfc, box, _company, _address = setup(factory, ws)
    inbox = Inbox()
    inbox.mail = [mail("<n1@x>", "newsletter@shop.example", "Sale", "Please unsubscribe from us")]
    counts = run(factory, ws, box, inbox)
    assert counts["ours"] == 0
    with factory(ws) as uow:
        assert not uow.inbound.known("<n1@x>")
        assert not uow.suppressions.is_email_suppressed("newsletter@shop.example")


def test_an_ordinary_reply_is_kept_for_a_person_and_changes_nothing(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    _first, rfc, box, company_id, _address_id = setup(factory, ws)
    inbox = Inbox()
    inbox.mail = [
        mail(
            "<o1@x>", "jane@acme.com", "Re: leeds solar forecasts", "Tell me more.", in_reply_to=rfc
        )
    ]
    counts = run(factory, ws, box, inbox)
    assert counts["ours"] == 1 and counts["unsubscribe"] == 0
    with factory(ws) as uow:
        assert uow.inbound.known("<o1@x>")
        assert not uow.suppressions.is_email_suppressed("jane@acme.com")
        assert uow.companies.get(company_id).status is CompanyStatus.IN_SEQUENCE
    assert InboundCategory.OTHER  # stored as other
