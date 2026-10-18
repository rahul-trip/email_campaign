"""Messages: one row per touch, with the text we wrote and the text that was actually sent."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select

from outbound.db.models import CompanyRow, MessageRow
from outbound.db.repositories.base import ScopedRepository, snapshot
from outbound.domain.actors import SYSTEM
from outbound.domain.entities import Message
from outbound.domain.enums import EntityType, MessageState
from outbound.domain.state_machines import MESSAGE

# Columns a transition may set alongside the new state.
TRANSITION_FIELDS = frozenset(
    {
        "remote_draft_id",
        "rfc_message_id",
        "in_reply_to",
        "sent_at",
        "scheduled_for",
        "final_body",
        "edit_distance",
        "mailbox_id",
    }
)


class MessageRepository(ScopedRepository):
    def create(
        self,
        *,
        company_id: str,
        contact_id: str,
        contact_email_id: str,
        step: int,
        subject: str,
        generated_body: str,
        state: MessageState = MessageState.GENERATED,
        snippets: dict[str, Any] | None = None,
        lint_report: dict[str, Any] | None = None,
        mailbox_id: str | None = None,
        in_reply_to: str | None = None,
        actor: str = SYSTEM,
    ) -> Message:
        row = MessageRow(
            workspace_id=self._workspace_id,
            company_id=company_id,
            contact_id=contact_id,
            contact_email_id=contact_email_id,
            step=step,
            subject=subject,
            generated_body=generated_body,
            state=state,
            snippets=snippets,
            lint_report=lint_report,
            mailbox_id=mailbox_id,
            in_reply_to=in_reply_to,
        )
        self._session.add(row)
        self._session.flush()
        self._events.append(
            EntityType.MESSAGE, row.id, "created", actor, {"step": step, "state": state.value}
        )
        return snapshot(row, Message)

    def get(self, message_id: str) -> Message:
        return snapshot(self._row(MessageRow, message_id), Message)

    def for_company(self, company_id: str) -> list[Message]:
        stmt = (
            select(MessageRow)
            .where(
                MessageRow.workspace_id == self._workspace_id, MessageRow.company_id == company_id
            )
            .order_by(MessageRow.step, MessageRow.id)
        )
        return [snapshot(row, Message) for row in self._session.scalars(stmt)]

    def for_contact(self, contact_id: str) -> list[Message]:
        stmt = (
            select(MessageRow)
            .where(
                MessageRow.workspace_id == self._workspace_id, MessageRow.contact_id == contact_id
            )
            .order_by(MessageRow.step, MessageRow.id)
        )
        return [snapshot(row, Message) for row in self._session.scalars(stmt)]

    def drafted_in_mailbox(self, limit: int) -> list[Message]:
        """Drafts the engine saved in a mailbox, newest first. Messages imported from the old
        workbook are 'drafted' too but have no mailbox draft, and can never match a sent mail."""
        stmt = (
            select(MessageRow)
            .where(
                MessageRow.workspace_id == self._workspace_id,
                MessageRow.state == MessageState.DRAFTED,
                MessageRow.remote_draft_id.is_not(None),
            )
            .order_by(MessageRow.updated_at.desc(), MessageRow.id.desc())
            .limit(limit)
        )
        return [snapshot(row, Message) for row in self._session.scalars(stmt)]

    def rfc_id_taken(self, rfc_message_id: str) -> bool:
        stmt = select(MessageRow.id).where(
            MessageRow.workspace_id == self._workspace_id,
            MessageRow.rfc_message_id == rfc_message_id,
        )
        return self._session.scalars(stmt).first() is not None

    def edited_examples(self, campaign_id: str, limit: int) -> list[Message]:
        """The most recent emails in a campaign that the operator changed before sending."""
        stmt = (
            select(MessageRow)
            .join(CompanyRow, CompanyRow.id == MessageRow.company_id)
            .where(
                MessageRow.workspace_id == self._workspace_id,
                CompanyRow.campaign_id == campaign_id,
                MessageRow.final_body.is_not(None),
                MessageRow.edit_distance > 0,
            )
            .order_by(MessageRow.updated_at.desc(), MessageRow.id.desc())
            .limit(limit)
        )
        return [snapshot(row, Message) for row in self._session.scalars(stmt)]

    def in_state(self, state: MessageState, limit: int = 100) -> list[Message]:
        stmt = (
            select(MessageRow)
            .where(MessageRow.workspace_id == self._workspace_id, MessageRow.state == state)
            .order_by(MessageRow.created_at, MessageRow.id)
            .limit(limit)
        )
        return [snapshot(row, Message) for row in self._session.scalars(stmt)]

    def transition(
        self,
        message_id: str,
        to: MessageState,
        *,
        expected_version: int,
        actor: str = SYSTEM,
        set_fields: Mapping[str, Any] | None = None,
    ) -> Message:
        row = self._row(MessageRow, message_id)
        self._check_version(row, expected_version)
        MESSAGE.check(row.state, to)
        extra = dict(set_fields or {})
        unknown = set(extra) - TRANSITION_FIELDS
        if unknown:
            raise ValueError(f"cannot set {sorted(unknown)} during a transition")
        previous = row.state
        row.state = to
        for name, value in extra.items():
            setattr(row, name, value)
        self._flush()
        self._events.append(
            EntityType.MESSAGE,
            row.id,
            "status_changed",
            actor,
            {"from": previous.value, "to": to.value},
        )
        return snapshot(row, Message)
