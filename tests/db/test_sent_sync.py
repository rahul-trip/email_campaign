"""Stage 9: matching the Sent folder to drafts, on fixture mailboxes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import (
    CompanySource,
    CompanyStatus,
    ContactSource,
    EmailStatus,
    EntityType,
    MessageState,
    Provenance,
)
from outbound.providers.ports import SentMessage
from outbound.stages.sync import SentSync, normal_subject

BODY = "Hi Jane,\n\nI saw the Leeds office. Would a call help?\n\nSam Lee\n\n--\nQuantra, Austin."


class SentFolder:
    address = "sam@quantra.example"

    def __init__(self, sent: list[SentMessage] | None = None) -> None:
        self.sent = sent or []
        self.asked_since: datetime | None = None

    def list_sent(self, since: datetime) -> list[SentMessage]:
        self.asked_since = since
        return [m for m in self.sent if m.sent_at >= since]

    def list_inbox(self, since: datetime) -> list[Any]:
        return []

    def append_draft(self, draft: Any) -> str:
        raise AssertionError("sync never writes drafts")

    def draft_exists(self, remote_draft_id: str) -> bool:
        return False

    def delete_draft(self, remote_draft_id: str) -> int:
        return 0


def drafted(
    factory: UnitOfWorkFactory,
    ws: str,
    *,
    domain: str = "acme.com",
    subject: str = "leeds solar forecasts",
    to: str | None = None,
) -> str:
    """A drafted touch-1 message. Returns its id."""
    with factory(ws) as uow:
        company = uow.companies.create(domain=domain, source=CompanySource.MANUAL)
        version = company.row_version
        for step in (
            CompanyStatus.RESEARCHED,
            CompanyStatus.QUALIFIED,
            CompanyStatus.CONTACTS_FOUND,
            CompanyStatus.EMAIL_READY,
            CompanyStatus.COPY_READY,
            CompanyStatus.APPROVED,
            CompanyStatus.IN_SEQUENCE,
        ):
            version = uow.companies.transition(
                company.id, step, expected_version=version
            ).row_version
        contact = uow.contacts.add(company.id, rank=1, source=ContactSource.SITE, full_name="J D")
        address = uow.emails.add(
            contact.id,
            to or f"jane@{domain}",
            Provenance.API_DATABASE,
            status=EmailStatus.VALID,
            is_primary=True,
        )
        message = uow.messages.create(
            company_id=company.id,
            contact_id=contact.id,
            contact_email_id=address.id,
            step=0,
            subject=subject,
            generated_body=BODY,
        )
        message = uow.messages.transition(
            message.id, MessageState.APPROVED, expected_version=message.row_version
        )
        message = uow.messages.transition(
            message.id,
            MessageState.DRAFTED,
            expected_version=message.row_version,
            set_fields={"remote_draft_id": f"<{message.id}@q>"},
        )
        uow.commit()
        return message.id


def sent_mail(
    ident: str,
    *,
    to: str = "jane@acme.com",
    subject: str = "leeds solar forecasts",
    body: str = BODY,
    minutes: float = 30,
) -> SentMessage:
    return SentMessage(
        rfc_message_id=ident,
        to_address=to,
        subject=subject,
        sent_at=datetime.now(UTC) + timedelta(minutes=minutes),
        body=body,
    )


def run(factory: UnitOfWorkFactory, ws: str, folder: SentFolder) -> dict[str, int]:
    return SentSync(factory, ws, folder).run()


def state(factory: UnitOfWorkFactory, ws: str, message_id: str):  # type: ignore[no-untyped-def]
    with factory(ws) as uow:
        return uow.messages.get(message_id)


def test_subjects_are_compared_without_reply_prefixes_or_spacing() -> None:
    assert normal_subject("RE:  Leeds   Solar Forecasts ") == "leeds solar forecasts"
    assert normal_subject("Fwd: Re: x") == "x"
    assert normal_subject("AW: hello") == "hello"


def test_an_unedited_send_is_matched_and_scores_zero(factory: UnitOfWorkFactory, ws: str) -> None:
    mid = drafted(factory, ws)
    folder = SentFolder([sent_mail("<s1@quantra.example>")])
    counts = run(factory, ws, folder)
    assert counts == {"drafts": 1, "matched": 1, "ambiguous": 0, "waiting": 0}
    message = state(factory, ws, mid)
    assert message.state is MessageState.SENT
    assert message.rfc_message_id == "<s1@quantra.example>"
    assert message.edit_distance == 0.0
    assert message.final_body == BODY
    assert message.sent_at is not None


def test_an_edited_send_keeps_the_body_that_went_out_and_how_far_it_moved(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    mid = drafted(factory, ws)
    edited = BODY.replace("Would a call help?", "Free for a quick chat on Thursday?")
    run(factory, ws, SentFolder([sent_mail("<s1@x>", body=edited)]))
    message = state(factory, ws, mid)
    assert message.state is MessageState.SENT
    assert message.final_body == edited
    assert message.edit_distance is not None and 0 < message.edit_distance < 0.5
    assert message.generated_body == BODY


def test_a_reply_prefix_and_recipient_case_do_not_prevent_a_match(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    mid = drafted(factory, ws)
    mail = sent_mail("<s1@x>", to="Jane@Acme.com", subject="Re: Leeds solar forecasts")
    run(factory, ws, SentFolder([mail]))
    assert state(factory, ws, mid).state is MessageState.SENT


def test_nothing_sent_yet_leaves_the_draft_waiting(factory: UnitOfWorkFactory, ws: str) -> None:
    mid = drafted(factory, ws)
    counts = run(factory, ws, SentFolder([]))
    assert counts["waiting"] == 1
    assert state(factory, ws, mid).state is MessageState.DRAFTED


def test_a_mail_to_someone_else_or_with_another_subject_is_not_a_match(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    mid = drafted(factory, ws)
    others = [
        sent_mail("<a@x>", to="other@acme.com"),
        sent_mail("<b@x>", subject="something else"),
    ]
    run(factory, ws, SentFolder(others))
    assert state(factory, ws, mid).state is MessageState.DRAFTED


def test_a_mail_sent_before_the_draft_existed_is_not_a_match(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    mid = drafted(factory, ws)
    old = sent_mail("<old@x>", minutes=-600)
    counts = run(factory, ws, SentFolder([old]))
    assert counts["waiting"] == 1
    assert state(factory, ws, mid).state is MessageState.DRAFTED


def test_two_sent_mails_for_one_draft_are_ambiguous_and_flagged_once(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    mid = drafted(factory, ws)
    folder = SentFolder([sent_mail("<s1@x>"), sent_mail("<s2@x>", minutes=45)])
    assert run(factory, ws, folder)["ambiguous"] == 1
    assert run(factory, ws, folder)["ambiguous"] == 1
    assert state(factory, ws, mid).state is MessageState.DRAFTED
    with factory(ws) as uow:
        events = uow.events.for_entity(EntityType.MESSAGE, mid)
    flags = [e for e in events if e.type == "sync_ambiguous"]
    assert len(flags) == 1
    assert flags[0].data["candidates"] == ["<s1@x>", "<s2@x>"]


def test_one_sent_mail_that_fits_two_drafts_settles_neither(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    """Touch 1 and a follow-up to the same person share an address and (after "Re:") a subject."""
    first = drafted(factory, ws)
    with factory(ws) as uow:
        original = uow.messages.get(first)
        follow_up = uow.messages.create(
            company_id=original.company_id,
            contact_id=original.contact_id,
            contact_email_id=original.contact_email_id,
            step=1,
            subject="Re: leeds solar forecasts",
            generated_body="Nudge.",
        )
        follow_up = uow.messages.transition(
            follow_up.id, MessageState.APPROVED, expected_version=follow_up.row_version
        )
        follow_up = uow.messages.transition(
            follow_up.id,
            MessageState.DRAFTED,
            expected_version=follow_up.row_version,
            set_fields={"remote_draft_id": "<follow-up@q>"},
        )
        uow.commit()
    counts = run(factory, ws, SentFolder([sent_mail("<s1@x>")]))
    assert counts["ambiguous"] == 2 and counts["matched"] == 0
    assert state(factory, ws, first).state is MessageState.DRAFTED
    assert state(factory, ws, follow_up.id).state is MessageState.DRAFTED


def test_each_draft_finds_its_own_mail_when_several_are_pending(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    a = drafted(factory, ws, domain="acme.com")
    b = drafted(factory, ws, domain="beta.com")
    folder = SentFolder(
        [sent_mail("<a@x>", to="jane@acme.com"), sent_mail("<b@x>", to="jane@beta.com")]
    )
    assert run(factory, ws, folder)["matched"] == 2
    assert state(factory, ws, a).rfc_message_id == "<a@x>"
    assert state(factory, ws, b).rfc_message_id == "<b@x>"


def test_a_settled_message_is_not_looked_at_again(factory: UnitOfWorkFactory, ws: str) -> None:
    drafted(factory, ws)
    folder = SentFolder([sent_mail("<s1@x>")])
    run(factory, ws, folder)
    assert run(factory, ws, folder)["drafts"] == 0


def test_with_no_drafts_the_mailbox_is_not_even_opened(factory: UnitOfWorkFactory, ws: str) -> None:
    folder = SentFolder([sent_mail("<s1@x>")])
    assert run(factory, ws, folder)["drafts"] == 0
    assert folder.asked_since is None
