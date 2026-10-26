"""Reading each mailbox's inbox for the two replies that must be acted on (Phase 4a).

An opt-out ("unsubscribe", "remove me") suppresses the person and stops every email to them. A
hard bounce marks the address invalid, suppresses it and lets the lead go on to the next
person. Both are decided by rules (``outbound.domain.inbox``). Everything else that answers one
of our emails is kept as ``other`` for a person; mail that is not about our emails is ignored
and never stored.

A tick job: each pass reads what arrived since the last one (with an hour of overlap) and skips
what it has already recorded, so running twice, or two workers at once, does the same thing.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timedelta

from outbound.db.types import utcnow
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.actors import SYSTEM
from outbound.domain.entities import ContactEmail, Message
from outbound.domain.enums import InboundCategory
from outbound.domain.inbox import classify
from outbound.logging import get_logger
from outbound.providers.errors import ProviderError
from outbound.providers.ports import InboundMessage
from outbound.services.privacy import PrivacyService
from outbound.stages.mailboxes import Mailboxes, MailboxUnavailable

log = get_logger(__name__)

FIRST_LOOK = timedelta(days=7)
OVERLAP = timedelta(hours=1)
_ID = re.compile(r"<[^<>\s]+>")


class InboxSync:
    name = "inbox_sync"

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        workspace_id: str,
        mailboxes: Mailboxes,
        privacy: PrivacyService,
        *,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._uow = uow_factory
        self._workspace_id = workspace_id
        self._mailboxes = mailboxes
        self._privacy = privacy
        self._now = now

    def run(self) -> dict[str, int]:
        counts = {"read": 0, "ours": 0, "unsubscribe": 0, "hard_bounce": 0}
        try:
            opened = self._mailboxes.all_open()
        except MailboxUnavailable:
            return counts
        for mailbox_id, mailbox in opened:
            try:
                arrived = mailbox.list_inbox(self._since(mailbox_id))
            except ProviderError as error:  # one broken mailbox must not stop the others
                log.warning(
                    "inbox_sync_mailbox_failed", mailbox_id=mailbox_id, reason=str(error)[:200]
                )
                continue
            for item in sorted(arrived, key=lambda m: m.received_at):
                counts["read"] += 1
                category = self._handle(mailbox_id, item)
                if category is not None:
                    counts["ours"] += 1
                    if category.value in counts:
                        counts[category.value] += 1
        return counts

    def _since(self, mailbox_id: str | None) -> datetime:
        if mailbox_id is not None:
            with self._uow(self._workspace_id) as uow:
                latest = uow.inbound.latest(mailbox_id)
            if latest is not None:
                return latest - OVERLAP
        return self._now() - FIRST_LOOK

    # ------------------------------------------------------------------ one message

    def _handle(self, mailbox_id: str | None, item: InboundMessage) -> InboundCategory | None:
        with self._uow(self._workspace_id) as uow:
            if uow.inbound.known(item.rfc_message_id):
                return None
        verdict = classify(item.from_address, item.subject, item.body)
        found = self._match(item, verdict.failed_recipient)
        if found is None:
            return None  # not about one of our emails
        sent, address = found
        inbound_id: str | None = None
        with self._uow(self._workspace_id) as uow:
            if mailbox_id is not None:
                contact_id = address.contact_id if address else (sent.contact_id if sent else None)
                company_id = (
                    sent.company_id
                    if sent
                    else uow.contacts.get(contact_id).company_id
                    if contact_id
                    else None
                )
                inbound_id = uow.inbound.add(
                    mailbox_id=mailbox_id,
                    rfc_message_id=item.rfc_message_id,
                    received_at=item.received_at,
                    category=verdict.category,
                    confidence=verdict.confidence,
                    from_address=item.from_address,
                    body_excerpt=item.body[:500],
                    message_id=sent.id if sent else None,
                    company_id=company_id,
                    contact_id=contact_id,
                )
                uow.commit()
        acted = False
        if verdict.category is InboundCategory.UNSUBSCRIBE and address is not None:
            self._privacy.suppress_contact(address.contact_id, actor=SYSTEM)
            acted = True
        elif verdict.category is InboundCategory.HARD_BOUNCE and address is not None:
            self._privacy.bounced(address.id, actor=SYSTEM)
            acted = True
        if acted and inbound_id is not None:
            with self._uow(self._workspace_id) as uow:
                uow.inbound.mark_handled(inbound_id, self._now())
                uow.commit()
        log.info("inbound_handled", category=verdict.category.value, acted=acted)
        return verdict.category

    def _match(
        self, item: InboundMessage, failed_recipient: str | None
    ) -> tuple[Message | None, ContactEmail | None] | None:
        """Which of our emails this answers: by threading headers first, then by the address
        that bounced, then by who wrote."""
        referenced = _ID.findall(" ".join(filter(None, [item.in_reply_to, item.references])))
        with self._uow(self._workspace_id) as uow:
            for rfc_id in referenced:
                sent = uow.messages.by_rfc_id(rfc_id)
                if sent is not None:
                    return sent, uow.emails.get(sent.contact_email_id)
            for candidate in (failed_recipient, item.from_address):
                if candidate:
                    address = uow.emails.by_address(candidate)
                    if address is not None and uow.messages.sent_to(address.id):
                        return None, address
        return None
