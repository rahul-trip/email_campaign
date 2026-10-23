"""Contract for the Mailbox port (Phase 6c): IMAP, Microsoft Graph and the Gmail API behave the
same to the delivery stage and the Sent sync.

A subclass gives ``world()``: a fresh mailbox over a fake of its server, and a way to put a
message in the Sent folder as if the person had sent it from their mail program.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from outbound.providers.ports import Mailbox, OutgoingDraft

SINCE = datetime(2026, 10, 10, tzinfo=UTC)


class PutSent(Protocol):
    def __call__(
        self, *, message_id: str, to: str, subject: str, sent_at: datetime, body: str
    ) -> None: ...


@dataclass
class World:
    mailbox: Mailbox
    put_sent: PutSent


def draft(n: int, *, to: str = "jane@acme.com") -> OutgoingDraft:
    return OutgoingDraft(
        to_address=to,
        subject=f"grid demand {n}",
        body=f"Hello Jane, note {n}.",
        message_id=f"<draft-{n}.outbound@quantra.example>",
    )


class MailboxContract:
    def world(self) -> World:
        raise NotImplementedError

    def test_a_saved_draft_keeps_our_message_id_and_can_be_found(self) -> None:
        box = self.world().mailbox
        assert box.draft_exists("<draft-1.outbound@quantra.example>") is False
        assert box.append_draft(draft(1)) == "<draft-1.outbound@quantra.example>"
        assert box.draft_exists("<draft-1.outbound@quantra.example>") is True
        assert box.draft_exists("<draft-2.outbound@quantra.example>") is False

    def test_deleting_removes_only_that_draft_and_twice_is_harmless(self) -> None:
        box = self.world().mailbox
        box.append_draft(draft(1))
        box.append_draft(draft(2))
        assert box.delete_draft("<draft-2.outbound@quantra.example>") == 1
        assert box.draft_exists("<draft-2.outbound@quantra.example>") is False
        assert box.draft_exists("<draft-1.outbound@quantra.example>") is True
        assert box.delete_draft("<draft-2.outbound@quantra.example>") == 0

    def test_sent_mail_since_a_time_comes_back_newest_first(self) -> None:
        world = self.world()
        for n, day in ((1, 9), (2, 12), (3, 14)):
            world.put_sent(
                message_id=f"<sent-{n}@quantra.example>",
                to="Jane@Acme.com",
                subject=f"subject {n}",
                sent_at=datetime(2026, 10, day, 9, 30, tzinfo=UTC),
                body=f"Hello Jane {n}",
            )
        sent = world.mailbox.list_sent(SINCE)
        assert [s.rfc_message_id for s in sent] == [
            "<sent-3@quantra.example>",
            "<sent-2@quantra.example>",
        ]
        newest = sent[0]
        assert newest.to_address == "jane@acme.com"
        assert newest.subject == "subject 3"
        assert newest.sent_at == datetime(2026, 10, 14, 9, 30, tzinfo=UTC)
        assert "Hello Jane 3" in newest.body

    def test_the_mailbox_knows_its_address(self) -> None:
        assert "@" in self.world().mailbox.address
