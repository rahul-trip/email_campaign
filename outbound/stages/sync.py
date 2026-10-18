"""Stage 9 (part): read the Sent folder and learn what was actually sent.

The operator sends drafts from their normal mail client, so the engine finds out by looking. A
sent mail belongs to a draft when it went to the same address, has the same subject once "Re:"
and spacing are ignored, and was sent after the draft was made. Exactly one match settles it:
the message becomes ``sent`` and keeps the body that went out, with how far it moved from what
the engine wrote. Anything less clear (two candidates either way) is left alone and flagged
once for the operator, because guessing would mark the wrong email as sent.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timedelta

from outbound.db.types import utcnow
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.actors import SYSTEM
from outbound.domain.editing import edit_distance
from outbound.domain.entities import Message
from outbound.domain.enums import EntityType, MessageState
from outbound.logging import get_logger
from outbound.providers.ports import Mailbox, SentMessage

log = get_logger(__name__)

CLOCK_SKEW = timedelta(minutes=5)  # the mail server's clock and ours may disagree a little
LOOK_BACK = timedelta(hours=1)
_PREFIX = re.compile(r"^\s*((re|fwd?|aw)\s*:\s*)+", re.IGNORECASE)


def normal_subject(subject: str) -> str:
    return " ".join(_PREFIX.sub("", subject).lower().split())


class SentSync:
    name = "sent_sync"

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        workspace_id: str,
        mailbox: Mailbox,
        *,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._uow = uow_factory
        self._workspace_id = workspace_id
        self._mailbox = mailbox
        self._now = now

    def run(self) -> dict[str, int]:
        with self._uow(self._workspace_id) as uow:
            drafts = [
                (m, uow.emails.get(m.contact_email_id).email)
                for m in uow.messages.in_state(MessageState.DRAFTED, 500)
            ]
        counts = {"drafts": len(drafts), "matched": 0, "ambiguous": 0, "waiting": 0}
        if not drafts:
            return counts

        earliest = min((m.updated_at for m, _ in drafts if m.updated_at), default=self._now())
        sent = self._mailbox.list_sent(earliest - CLOCK_SKEW - LOOK_BACK)

        candidates = {m.id: [s for s in sent if _fits(m, address, s)] for m, address in drafts}
        claimed: dict[str, list[str]] = defaultdict(list)
        for message_id, found in candidates.items():
            for item in found:
                claimed[item.rfc_message_id].append(message_id)

        for message, _address in drafts:
            found = candidates[message.id]
            if not found:
                counts["waiting"] += 1
            elif len(found) == 1 and len(claimed[found[0].rfc_message_id]) == 1:
                self._settle(message, found[0])
                counts["matched"] += 1
            else:
                self._flag(message, [s.rfc_message_id for s in found])
                counts["ambiguous"] += 1
        return counts

    def _settle(self, message: Message, sent: SentMessage) -> None:
        with self._uow(self._workspace_id) as uow:
            current = uow.messages.get(message.id)
            if current.state is not MessageState.DRAFTED:
                return
            if uow.session.execute(_taken(sent.rfc_message_id, self._workspace_id)).first():
                return  # that sent mail is already recorded against another message
            uow.messages.transition(
                message.id,
                MessageState.SENT,
                expected_version=current.row_version,
                actor=SYSTEM,
                set_fields={
                    "rfc_message_id": sent.rfc_message_id,
                    "sent_at": sent.sent_at,
                    "final_body": sent.body,
                    "edit_distance": edit_distance(current.generated_body, sent.body),
                },
            )
            uow.commit()

    def _flag(self, message: Message, candidates: list[str]) -> None:
        """Record the ambiguity once; ticks repeat every few hours."""
        with self._uow(self._workspace_id) as uow:
            seen = {e.type for e in uow.events.for_entity(EntityType.MESSAGE, message.id)}
            if "sync_ambiguous" in seen:
                return
            uow.events.append(
                EntityType.MESSAGE,
                message.id,
                "sync_ambiguous",
                SYSTEM,
                {"candidates": candidates, "action": "match by hand"},
            )
            uow.commit()
        log.warning("sent_sync_ambiguous", message_id=message.id, candidates=len(candidates))


def _fits(message: Message, address: str | None, sent: SentMessage) -> bool:
    if not address or not message.updated_at:
        return False
    return (
        sent.to_address.lower() == address.lower()
        and normal_subject(sent.subject) == normal_subject(message.subject)
        and sent.sent_at >= message.updated_at - CLOCK_SKEW
    )


def _taken(rfc_message_id: str, workspace_id: str):  # type: ignore[no-untyped-def]
    from sqlalchemy import select

    from outbound.db.models import MessageRow

    return select(MessageRow.id).where(
        MessageRow.workspace_id == workspace_id, MessageRow.rfc_message_id == rfc_message_id
    )
