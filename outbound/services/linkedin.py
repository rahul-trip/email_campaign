"""LinkedIn messages: written for the operator to paste by hand. Nothing is sent from here.

Drafts are written by the contacts step for confirmed decision-makers (see
``stages/contacts.py``); this service lists them, writes one on request, lets the operator edit,
skip and mark them sent, and holds a lead's email once its person was messaged on LinkedIn.
"""

from __future__ import annotations

from dataclasses import dataclass

from outbound.db.repositories.linkedin import LinkedInListing
from outbound.db.uow import UnitOfWork, UnitOfWorkFactory
from outbound.domain.actors import OPERATOR
from outbound.domain.entities import LinkedInMessage
from outbound.domain.enums import (
    WORKABLE_CONTACT_STATUSES,
    CompanyStatus,
    HoldReason,
    LinkedInState,
    MessageState,
)
from outbound.domain.errors import InvalidInput
from outbound.domain.sender import sender_for
from outbound.domain.state_machines import IllegalTransition
from outbound.metering.metered import call_scope
from outbound.providers.ports import LlmClient
from outbound.services.leads import LeadError
from outbound.stages.linkedin import LinkedInInput, write_linkedin

# Where the email has not left yet: sending a LinkedIn message holds it, to be released by hand.
_HOLDABLE = frozenset(
    {CompanyStatus.CONTACTS_FOUND, CompanyStatus.EMAIL_READY, CompanyStatus.COPY_READY}
)


@dataclass(frozen=True)
class LinkedInSent:
    message: LinkedInMessage
    email_held: bool  # the lead's email now waits until it is released


class LinkedInService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        workspace_id: str,
        *,
        llm: LlmClient | None = None,
        actor: str = OPERATOR,
    ) -> None:
        self._uow = uow_factory
        self._workspace_id = workspace_id
        self._llm = llm  # behind the meter
        self._actor = actor

    # ------------------------------------------------------------------ reading

    def for_company(self, company_id: str) -> list[LinkedInMessage]:
        with self._uow(self._workspace_id) as uow:
            uow.companies.get(company_id)  # NotFound for another workspace's lead
            return uow.linkedin.for_company(company_id)

    def page(
        self,
        state: LinkedInState,
        *,
        limit: int = 50,
        offset: int = 0,
        hot: bool | None = None,
        text: str | None = None,
        min_fit: int | None = None,
        no_email: bool | None = None,
        country: str | None = None,
        sort: str | None = None,
        direction: str | None = None,
    ) -> tuple[list[LinkedInListing], int]:
        with self._uow(self._workspace_id) as uow:
            return uow.linkedin.page(
                state,
                limit=limit,
                offset=offset,
                hot=hot,
                text=text,
                min_fit=min_fit,
                no_email=no_email,
                country=country,
                sort=sort,
                direction=direction,
            )

    # ------------------------------------------------------------------ writing a draft

    def write(self, contact_id: str, *, actor: str | None = None) -> LinkedInMessage:
        """Write (or rewrite) the note and message for one person who works at the lead."""
        actor = actor or self._actor
        if self._llm is None:
            raise LeadError("writing is not set up (no model key), so drafts cannot be written")
        with self._uow(self._workspace_id) as uow:
            contact = uow.contacts.get(contact_id)  # NotFound unless in this workspace
            company = uow.companies.get(contact.company_id)
            if contact.status not in WORKABLE_CONTACT_STATUSES:
                raise LeadError(
                    f"this person is {contact.status.value.replace('_', ' ')}: confirm that they"
                    " work here first"
                )
            if not contact.linkedin_url:
                raise LeadError("this person has no LinkedIn profile yet: use Find LinkedIn first")
            existing = uow.linkedin.for_contact(contact_id)
            if existing and existing.state is LinkedInState.SENT:
                raise LeadError("you already sent this person a LinkedIn message")
            workspace = uow.own_workspace.get()
            profile = dict(workspace.sender_profile) if workspace else {}
            campaign = uow.campaigns.get(company.campaign_id) if company.campaign_id else None
            mailbox = (
                uow.mailboxes.get(campaign.mailbox_id) if campaign and campaign.mailbox_id else None
            )
            mailbox = mailbox or uow.mailboxes.default()
            notes = "\n".join(n.body for n in uow.notes.for_company(company.id))
        sender = sender_for(profile, mailbox.sender if mailbox else None)
        if not profile.get("reviewed_at") or not str(sender.get("signature_name") or "").strip():
            raise LeadError("review and save your sender profile first (Settings → Sender profile)")
        first = contact.first_name or next(iter((contact.full_name or "").split()), "")
        if not first:
            raise LeadError("this person has no name yet")
        with call_scope(company_id=company.id, contact_id=contact_id):
            draft = write_linkedin(
                self._llm,
                LinkedInInput(
                    sender=sender,
                    first_name=first,
                    title=contact.title or "",
                    company_name=company.name or company.domain,
                    research=company.research or {},
                    notes=notes,
                ),
            )
        with self._uow(self._workspace_id) as uow:
            current = uow.linkedin.for_contact(contact_id)
            if current is None:
                saved = uow.linkedin.create(
                    company_id=company.id,
                    contact_id=contact_id,
                    note=draft.note,
                    message=draft.message,
                    issues=list(draft.issues),
                    actor=actor,
                )
            else:
                saved = uow.linkedin.rewrite(
                    current.id,
                    note=draft.note,
                    message=draft.message,
                    issues=list(draft.issues),
                    actor=actor,
                )
            uow.commit()
            return saved

    def edit(
        self, linkedin_id: str, *, note: str, message: str, actor: str | None = None
    ) -> LinkedInMessage:
        actor = actor or self._actor
        note, message = note.strip(), message.strip()
        if not note or not message:
            raise InvalidInput("write both the connection note and the message")
        with self._uow(self._workspace_id) as uow:
            current = uow.linkedin.get(linkedin_id)
            if current.state is LinkedInState.SENT:
                raise LeadError("this message was sent: it cannot be changed")
            saved = uow.linkedin.edit(linkedin_id, note=note, message=message, actor=actor)
            uow.commit()
            return saved

    def skip(self, linkedin_id: str, *, actor: str | None = None) -> LinkedInMessage:
        return self._move(linkedin_id, LinkedInState.SKIPPED, actor or self._actor)

    def restore(self, linkedin_id: str, *, actor: str | None = None) -> LinkedInMessage:
        return self._move(linkedin_id, LinkedInState.DRAFTED, actor or self._actor)

    def _move(self, linkedin_id: str, to: LinkedInState, actor: str) -> LinkedInMessage:
        with self._uow(self._workspace_id) as uow:
            try:
                moved = uow.linkedin.transition(linkedin_id, to, actor=actor)
            except IllegalTransition as error:  # a sent message is final
                raise LeadError(str(error)) from None
            uow.commit()
            return moved

    # ------------------------------------------------------------------ sending

    def mark_sent(self, linkedin_id: str, *, actor: str | None = None) -> LinkedInSent:
        """The operator pasted it into LinkedIn and sent it. The lead's email then waits.

        A lead whose email is still before the mailbox is held (an email waiting for review is
        cancelled, and written again when the hold is released). One already in the mailbox, or
        sent, is left alone: the message is only recorded.
        """
        actor = actor or self._actor
        with self._uow(self._workspace_id) as uow:
            current = uow.linkedin.get(linkedin_id)
            try:
                sent = uow.linkedin.transition(linkedin_id, LinkedInState.SENT, actor=actor)
            except IllegalTransition as error:
                raise LeadError(
                    "this message was already marked sent"
                    if current.state is LinkedInState.SENT
                    else str(error)
                ) from None
            held = self._hold_email(uow, current, actor)
            uow.commit()
            return LinkedInSent(sent, held)

    @staticmethod
    def _hold_email(uow: UnitOfWork, message: LinkedInMessage, actor: str) -> bool:
        company = uow.companies.get(message.company_id)
        if company.status not in _HOLDABLE:
            return False
        for email in uow.messages.for_company(company.id):
            if email.state is MessageState.GENERATED:
                uow.messages.transition(
                    email.id,
                    MessageState.CANCELLED,
                    expected_version=email.row_version,
                    actor=actor,
                )
        uow.companies.transition(
            company.id,
            CompanyStatus.HELD,
            expected_version=company.row_version,
            actor=actor,
            reason="messaged on LinkedIn: the email waits until you release it",
            hold_reason=HoldReason.LINKEDIN_CONTACTED,
            next_action_at=None,
        )
        return True
