"""Stage 7: a person reads each generated email and approves, edits or rejects it.

Nothing reaches the mailbox without passing through here. An edit is stored next to the text the
engine wrote (``final_body`` beside ``generated_body``) with how far it moved, which is what
later teaches the copywriter. The country footer is legal text, so an edit that removes it is
refused.
"""

from __future__ import annotations

from dataclasses import dataclass

from outbound.db.errors import ConcurrencyConflict, NotFound
from outbound.db.uow import UnitOfWork, UnitOfWorkFactory
from outbound.domain.actors import OPERATOR
from outbound.domain.editing import edit_distance
from outbound.domain.entities import Company, Contact, ContactEmail, Message
from outbound.domain.enums import CompanyStatus, EntityType, MessageState

FOOTER_MARK = "\n\n--\n"


class ReviewError(Exception):
    """The review action cannot be done; the message says why in plain words."""


@dataclass(frozen=True)
class QueueItem:
    message: Message
    company: Company
    contact: Contact
    address: ContactEmail

    @property
    def flagged(self) -> bool:
        return bool((self.message.lint_report or {}).get("flagged"))


@dataclass(frozen=True)
class ReviewDetail:
    item: QueueItem
    notes: list[str]


def footer_of(body: str) -> str | None:
    _, mark, footer = body.partition(FOOTER_MARK)
    return footer.strip() if mark else None


class ReviewService:
    def __init__(self, uow_factory: UnitOfWorkFactory, workspace_id: str) -> None:
        self._uow = uow_factory
        self._workspace_id = workspace_id

    def queue(self, limit: int = 100) -> list[QueueItem]:
        with self._uow(self._workspace_id) as uow:
            return [
                self._item(uow, m) for m in uow.messages.in_state(MessageState.GENERATED, limit)
            ]

    def resolve(self, ref: str) -> str:
        """A full message id, or a unique start of one, from what the operator typed."""
        with self._uow(self._workspace_id) as uow:
            matches = [
                m.id
                for state in (MessageState.GENERATED, MessageState.APPROVED)
                for m in uow.messages.in_state(state, 500)
                if m.id.startswith(ref)
            ]
        if len(matches) != 1:
            raise ReviewError(
                f"{ref!r} matches {len(matches)} messages waiting for review; use more characters"
                if matches
                else f"no message waiting for review starts with {ref!r}"
            )
        return matches[0]

    def show(self, message_id: str) -> ReviewDetail:
        with self._uow(self._workspace_id) as uow:
            item = self._item(uow, self._message(uow, message_id))
            notes = [n.body for n in uow.notes.for_company(item.company.id)]
        return ReviewDetail(item, notes)

    def approve(
        self,
        message_id: str,
        *,
        edited_body: str | None = None,
        expected_version: int | None = None,
        actor: str = OPERATOR,
    ) -> Message:
        with self._uow(self._workspace_id) as uow:
            message = self._pending(uow, message_id)
            if expected_version is not None and message.row_version != expected_version:
                raise ConcurrencyConflict("the message changed since you opened it")
            fields: dict[str, object] = {}
            edited = edited_body.strip() if edited_body is not None else None
            if edited is not None and edited != message.generated_body.strip():
                self._check_footer(message, edited)
                fields = {
                    "final_body": edited,
                    "edit_distance": edit_distance(message.generated_body, edited),
                }
            approved = uow.messages.transition(
                message.id,
                MessageState.APPROVED,
                expected_version=message.row_version,
                actor=actor,
                set_fields=fields,
            )
            if fields:
                uow.events.append(
                    EntityType.MESSAGE,
                    message.id,
                    "edited",
                    actor,
                    {"edit_distance": fields["edit_distance"]},
                )
            self._move_company(uow, message.company_id, CompanyStatus.APPROVED, actor, "approved")
            uow.commit()
            return approved

    def reject(self, message_id: str, reason: str, *, actor: str = OPERATOR) -> Message:
        if not reason.strip():
            raise ReviewError("say why it is rejected: the reason is kept with the lead")
        with self._uow(self._workspace_id) as uow:
            message = self._pending(uow, message_id)
            rejected = uow.messages.transition(
                message.id,
                MessageState.REJECTED,
                expected_version=message.row_version,
                actor=actor,
            )
            uow.events.append(
                EntityType.MESSAGE, message.id, "rejected", actor, {"reason": reason.strip()}
            )
            self._move_company(
                uow, message.company_id, CompanyStatus.REJECTED, actor, reason.strip()
            )
            uow.commit()
            return rejected

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _message(uow: UnitOfWork, message_id: str) -> Message:
        try:
            return uow.messages.get(message_id)
        except NotFound:
            raise ReviewError(f"there is no message {message_id!r}") from None

    def _pending(self, uow: UnitOfWork, message_id: str) -> Message:
        message = self._message(uow, message_id)
        if message.state is not MessageState.GENERATED:
            raise ReviewError(f"the message is {message.state.value}, not waiting for review")
        return message

    @staticmethod
    def _check_footer(message: Message, edited: str) -> None:
        footer = footer_of(message.generated_body)
        if footer and footer not in edited:
            raise ReviewError(
                "the edit removes the required footer: keep the text after the '--' line"
            )

    @staticmethod
    def _move_company(
        uow: UnitOfWork, company_id: str, to: CompanyStatus, actor: str, reason: str
    ) -> None:
        company = uow.companies.get(company_id)
        if company.status is not CompanyStatus.COPY_READY:
            raise ReviewError(f"the company is {company.status.value}, not copy_ready")
        try:
            uow.companies.transition(
                company_id, to, expected_version=company.row_version, actor=actor, reason=reason
            )
        except ConcurrencyConflict:
            raise ReviewError("the lead changed while you were reviewing it; try again") from None

    @staticmethod
    def _item(uow: UnitOfWork, message: Message) -> QueueItem:
        return QueueItem(
            message,
            uow.companies.get(message.company_id),
            uow.contacts.get(message.contact_id),
            uow.emails.get(message.contact_email_id),
        )
