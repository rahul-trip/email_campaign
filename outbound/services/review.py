"""Stage 7: a person reads each generated email and approves, edits or rejects it.

Nothing reaches the mailbox without passing through here. An edit is stored next to the text the
engine wrote (``final_body`` beside ``generated_body``) with how far it moved, which is what
later teaches the copywriter. The country footer is legal text, so an edit that removes it is
refused.
"""

from __future__ import annotations

from dataclasses import dataclass

from outbound.db.errors import ConcurrencyConflict, NotFound
from outbound.db.types import utcnow
from outbound.db.uow import UnitOfWork, UnitOfWorkFactory
from outbound.domain.actors import OPERATOR
from outbound.domain.copy_lint import LintRules
from outbound.domain.editing import edit_distance
from outbound.domain.entities import Company, Contact, ContactEmail, Message
from outbound.domain.enums import (
    CompanyStatus,
    ContactStatus,
    EmailStatus,
    EntityType,
    MessageState,
    UsageStep,
)
from outbound.metering.metered import call_scope
from outbound.metering.quota import credit_left
from outbound.providers.ports import LlmClient
from outbound.stages.copy.graph import Revision, revise_email

FOOTER_MARK = "\n\n--\n"


class ReviewError(Exception):
    """The review action cannot be done; the message says why in plain words."""


@dataclass(frozen=True)
class Skip:
    """A check the operator chose to skip that this email relies on."""

    kind: str  # country_policy, email_verification or works_here
    text: str


@dataclass(frozen=True)
class QueueItem:
    message: Message
    company: Company
    contact: Contact
    address: ContactEmail
    skips: tuple[Skip, ...] = ()

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
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        workspace_id: str,
        writer: LlmClient | None = None,
        *,
        actor: str = OPERATOR,
    ) -> None:
        self._uow = uow_factory
        self._workspace_id = workspace_id
        self._writer = writer  # the metered writer model, for revisions the operator asks for
        self._actor = actor

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
        acknowledge_skips: bool = False,
        actor: str | None = None,
    ) -> Message:
        """Approve an email. One that relies on a check you skipped (the country rule, the
        email check, or that the person works there) needs ``acknowledge_skips``: approval is
        where you confirm it, and what you confirmed is recorded."""
        actor = actor or self._actor
        with self._uow(self._workspace_id) as uow:
            message = self._pending(uow, message_id)
            if expected_version is not None and message.row_version != expected_version:
                raise ConcurrencyConflict("the message changed since you opened it")
            item = self._item(uow, message)
            if item.address.email and uow.suppressions.blocks(item.address.email):
                raise ReviewError("that address or its domain is now on the do-not-contact list")
            if item.skips and not acknowledge_skips:
                raise ReviewError(
                    "This email relies on checks you skipped: "
                    + "; ".join(s.text for s in item.skips)
                    + ". Confirm that you know before approving."
                )
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
            if item.skips:
                uow.events.append(
                    EntityType.MESSAGE,
                    message.id,
                    "approved_with_skips",
                    actor,
                    {"skips": [s.kind for s in item.skips]},
                )
            self._move_company(uow, message.company_id, CompanyStatus.APPROVED, actor, "approved")
            uow.commit()
            return approved

    def revise(
        self,
        message_id: str,
        instructions: str,
        *,
        current: str | None = None,
        actor: str | None = None,
    ) -> Revision:
        """Rewrite an email waiting for review the way the operator asks (tone, length, facts).

        ``current`` is the text in the editor, with any edits already made; without it the
        engine's text is revised. Nothing is saved: the result goes back into the editor, and
        approving it stores it as the operator's version (so it teaches the writer like an edit).
        The request is kept in the message's history.
        """
        actor = actor or self._actor
        ask_for = " ".join(instructions.split())
        if not ask_for:
            raise ReviewError("say what to change: the tone, the length, something to add...")
        if self._writer is None:
            raise ReviewError("no writer model is configured (LLM_MODEL or LLM_COPY_MODEL)")
        with self._uow(self._workspace_id) as uow:
            message = self._pending(uow, message_id)
            company = uow.companies.get(message.company_id)
            workspace = uow.workspace()
            sender = dict(workspace.sender_profile) if workspace else {}
            settings = dict(workspace.settings) if workspace else {}
            left, renews = credit_left(uow, UsageStep.REWRITE, utcnow())
        if not left:  # checked before the model is asked, so nothing is spent on a refusal
            raise ReviewError(
                f"no rewrite credits are left; they renew on {renews:%d %b}. "
                "Ask your admin for more in Settings → Plan and usage."
            )
        low = int(settings.get("email_min_words") or 120)
        high = int(settings.get("email_max_words") or 200)
        with call_scope(company_id=message.company_id, contact_id=message.contact_id):
            revision = revise_email(
                self._writer,
                email=(current or message.generated_body).strip(),
                instructions=instructions.strip(),
                sender=sender,
                research=company.research or {},
                subject=message.subject,
                rules=LintRules.with_length(low, max(low, high)),
            )
        footer = footer_of(message.generated_body)
        if footer and footer not in revision.body:  # code puts it back, but never trust that
            raise ReviewError("the revision lost the required footer; try again")
        with self._uow(self._workspace_id) as uow:
            uow.events.append(
                EntityType.MESSAGE, message.id, "revision_asked", actor, {"instructions": ask_for}
            )
            uow.usage.charge(UsageStep.REWRITE, message.company_id)
            uow.commit()
        return revision

    def reject(self, message_id: str, reason: str, *, actor: str | None = None) -> Message:
        actor = actor or self._actor
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
        company = uow.companies.get(message.company_id)
        contact = uow.contacts.get(message.contact_id)
        address = uow.emails.get(message.contact_email_id)
        return QueueItem(message, company, contact, address, _skips(uow, company, contact, address))


def _skips(
    uow: UnitOfWork, company: Company, contact: Contact, address: ContactEmail
) -> tuple[Skip, ...]:
    """The checks the operator skipped that an email to this address relies on."""
    skips: list[Skip] = []
    if not uow.workspace_settings().get("country_policy_enabled", True):
        skips.append(Skip("country_policy", "country rules are switched off for this workspace"))
    elif company.policy_skip_from:
        skips.append(
            Skip(
                "country_policy",
                f"the country rule is skipped for this lead from the"
                f" {company.policy_skip_from.value} step",
            )
        )
    if address.verification_skipped:
        said = (
            "it was not checked"
            if address.status is EmailStatus.UNVERIFIED
            else f"the check said {address.status.value.replace('_', ' ')}"
        )
        skips.append(Skip("email_verification", f"the address is used without proof ({said})"))
    confirmed = any(
        e.type == "status_changed" and e.data.get("from") == ContactStatus.UNCONFIRMED.value
        for e in uow.events.for_entities([(EntityType.CONTACT, contact.id)])
    )
    if confirmed:
        skips.append(
            Skip("works_here", "a search could not place this person here; you confirmed it")
        )
    return tuple(skips)
