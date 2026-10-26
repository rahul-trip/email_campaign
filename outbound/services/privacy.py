"""Stopping contact with someone, or with a whole company, and honouring erasure requests.

Each action is one database transaction. Drafts already saved in the mailbox are deleted only
after that transaction commits: if the mailbox is down, the database change still stands and the
result lists the drafts left to remove by hand (a draft that is never sent is a smaller harm than
an erasure request that failed half way).
"""

from __future__ import annotations

from dataclasses import dataclass

from outbound.db.uow import UnitOfWork, UnitOfWorkFactory
from outbound.domain.actors import OPERATOR
from outbound.domain.domains import registrable_domain
from outbound.domain.enums import (
    WORKABLE_CONTACT_STATUSES,
    CompanyStatus,
    ContactStatus,
    EmailStatus,
    MessageState,
    SuppressionKind,
    SuppressionReason,
)
from outbound.domain.errors import InvalidInput
from outbound.domain.state_machines import COMPANY, CONTACT, EMAIL
from outbound.logging import get_logger
from outbound.providers.errors import ProviderError
from outbound.services.forget import (
    DraftRef,
    drafts_of,
    forget_email,
    stop_contact,
    suppress_if_nobody_left,
)
from outbound.services.leads import LeadError
from outbound.stages.mailboxes import Mailboxes, MailboxUnavailable

log = get_logger(__name__)


@dataclass(frozen=True)
class PrivacyResult:
    found: bool  # whether we held anything about the person or company
    messages_cancelled: int = 0
    drafts_deleted: int = 0
    drafts_left: tuple[str, ...] = ()  # Message-IDs the operator must delete from the mailbox


@dataclass(frozen=True)
class DeleteResult:
    domain: str
    contacts_removed: int
    messages_removed: int
    drafts_deleted: int
    drafts_left: tuple[str, ...]
    domain_suppressed: bool


class PrivacyService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        workspace_id: str,
        mailboxes: Mailboxes | None = None,
        *,
        actor: str = OPERATOR,
    ) -> None:
        self._uow = uow_factory
        self._workspace_id = workspace_id
        self._mailboxes = mailboxes
        self._actor = actor

    def forget(self, email: str, *, actor: str | None = None) -> PrivacyResult:
        """Erase a person: suppress their address for good and remove what identifies them."""
        actor = actor or self._actor
        with self._uow(self._workspace_id) as uow:
            outcome = forget_email(uow, email, actor=actor)
            uow.commit()
        deleted, left = self._delete_drafts(outcome.drafts)
        # The address itself is deliberately not logged: erasure must not leave it in the logs.
        self._log("forget", actor, outcome.found, outcome.messages_cancelled, deleted, left)
        return PrivacyResult(outcome.found, outcome.messages_cancelled, deleted, left)

    def suppress_contact(self, contact_id: str, *, actor: str | None = None) -> PrivacyResult:
        """Never contact this person again (an opt-out). Their details are kept for the record."""
        actor = actor or self._actor
        with self._uow(self._workspace_id) as uow:
            contact = uow.contacts.get(contact_id)  # NotFound for another workspace's person
            for address in uow.emails.for_contact(contact_id):
                if address.email:
                    uow.suppressions.add(
                        SuppressionKind.EMAIL, address.email, SuppressionReason.OPT_OUT, actor=actor
                    )
            cancelled, draft_ids = stop_contact(uow, contact_id, actor)
            if CONTACT.allows(contact.status, ContactStatus.OPTED_OUT):
                uow.contacts.transition(
                    contact_id, ContactStatus.OPTED_OUT, actor=actor, reason="suppressed"
                )
            suppress_if_nobody_left(
                uow,
                contact.company_id,
                leaving=contact_id,
                actor=actor,
                reason="no contact left after an opt-out",
            )
            uow.commit()
        deleted, left = self._delete_drafts(tuple(draft_ids))
        self._log("suppress_contact", actor, True, cancelled, deleted, left, contact_id=contact_id)
        return PrivacyResult(True, cancelled, deleted, left)

    def bounced(self, contact_email_id: str, *, actor: str | None = None) -> PrivacyResult:
        """An address that cannot receive mail: stop using it, never try it again, and let the
        lead go on to the next person if there is one."""
        actor = actor or self._actor
        with self._uow(self._workspace_id) as uow:
            address = uow.emails.get(contact_email_id)
            contact = uow.contacts.get(address.contact_id)
            if EMAIL.allows(address.status, EmailStatus.INVALID):
                uow.emails.transition(contact_email_id, EmailStatus.INVALID, actor=actor)
            if address.email:
                uow.suppressions.add(
                    SuppressionKind.EMAIL, address.email, SuppressionReason.HARD_BOUNCE, actor=actor
                )
            for sent in uow.messages.sent_to(contact_email_id)[:1]:
                uow.messages.transition(
                    sent.id, MessageState.BOUNCED, expected_version=sent.row_version, actor=actor
                )
            cancelled, draft_ids = stop_contact(uow, contact.id, actor)
            if CONTACT.allows(contact.status, ContactStatus.BOUNCED):
                uow.contacts.transition(
                    contact.id, ContactStatus.BOUNCED, actor=actor, reason="hard bounce"
                )
            others = [
                c
                for c in uow.contacts.for_company(contact.company_id)
                if c.id != contact.id and c.status in WORKABLE_CONTACT_STATUSES
            ]
            company = uow.companies.get(contact.company_id)
            if others and COMPANY.allows(company.status, CompanyStatus.CONTACTS_FOUND):
                uow.companies.transition(
                    company.id,
                    CompanyStatus.CONTACTS_FOUND,
                    expected_version=company.row_version,
                    actor=actor,
                    reason="the address bounced; on to the next person",
                )
            uow.commit()
        deleted, left = self._delete_drafts(tuple(draft_ids))
        self._log("bounced", actor, True, cancelled, deleted, left, contact_id=contact.id)
        return PrivacyResult(True, cancelled, deleted, left)

    def suppress_company(self, company_id: str, *, actor: str | None = None) -> PrivacyResult:
        """Never contact anyone at this company's domain again."""
        actor = actor or self._actor
        with self._uow(self._workspace_id) as uow:
            company = uow.companies.get(company_id)
            uow.suppressions.add(
                SuppressionKind.DOMAIN, company.domain, SuppressionReason.OPT_OUT, actor=actor
            )
            cancelled, draft_ids = self._stop_everyone(uow, company_id, actor)
            current = uow.companies.get(company_id)
            if COMPANY.allows(current.status, CompanyStatus.SUPPRESSED):
                uow.companies.transition(
                    company_id,
                    CompanyStatus.SUPPRESSED,
                    expected_version=current.row_version,
                    actor=actor,
                    reason="domain suppressed by the operator",
                )
            uow.commit()
        deleted, left = self._delete_drafts(tuple(draft_ids))
        self._log("suppress_company", actor, True, cancelled, deleted, left, company_id=company_id)
        return PrivacyResult(True, cancelled, deleted, left)

    def suppress_value(self, value: str, *, actor: str | None = None) -> PrivacyResult:
        """Suppress an address or a domain, acting on the person or company if we hold them."""
        actor = actor or self._actor
        text = value.strip().lower()
        if not text:
            raise InvalidInput("give an email address or a domain")
        with self._uow(self._workspace_id) as uow:
            if "@" in text:
                known = uow.emails.by_address(text)
                person = known.contact_id if known else None
                if person is None:
                    uow.suppressions.add(
                        SuppressionKind.EMAIL, text, SuppressionReason.OPT_OUT, actor=actor
                    )
                    uow.commit()
                    return PrivacyResult(False)
                target: tuple[str, str] = ("contact", person)
            else:
                domain = registrable_domain(text) or text
                known_company = uow.companies.by_domain(domain)
                if known_company is None:
                    uow.suppressions.add(
                        SuppressionKind.DOMAIN, domain, SuppressionReason.OPT_OUT, actor=actor
                    )
                    uow.commit()
                    return PrivacyResult(False)
                target = ("company", known_company.id)
        if target[0] == "contact":
            return self.suppress_contact(target[1], actor=actor)
        return self.suppress_company(target[1], actor=actor)

    def delete_lead(
        self,
        company_id: str,
        *,
        confirm_domain: str,
        also_suppress_domain: bool = False,
        actor: str | None = None,
    ) -> DeleteResult:
        """Permanently remove a lead: its people, addresses, emails, notes and history.

        Three safeguards. The caller must type the lead's domain, so a wrong click cannot do it.
        A lead we have already emailed cannot be deleted, because the record of mail that left
        must stay (suppress it instead). Drafts waiting in the mailbox are deleted with it.
        Optionally the domain is also put on the do-not-contact list, so it is never added again.
        """
        actor = actor or self._actor
        with self._uow(self._workspace_id) as uow:
            company = uow.companies.get(company_id)  # NotFound for another workspace's lead
            if confirm_domain.strip().lower() != company.domain:
                raise InvalidInput(f"type the domain, {company.domain}, to confirm the deletion")
            messages = uow.messages.for_company(company_id)
            if any(m.state in (MessageState.SENT, MessageState.BOUNCED) for m in messages):
                raise LeadError(
                    "An email was sent to this lead, and the record of mail that has left must "
                    "stay. Use Suppress to stop all contact instead."
                )
            draft_ids = tuple(drafts_of(messages))
            contacts = uow.contacts.for_company(company_id)
            gone = uow.erasure.delete_company(
                company_id,
                actor=actor,
                note={
                    "domain": company.domain,
                    "status_was": company.status.value,
                    "contacts": len(contacts),
                    "messages": len(messages),
                    "domain_suppressed": also_suppress_domain,
                },
            )
            if also_suppress_domain:
                uow.suppressions.add(
                    SuppressionKind.DOMAIN, company.domain, SuppressionReason.MANUAL, actor=actor
                )
            uow.commit()
        deleted, left = self._delete_drafts(draft_ids)
        log.warning(  # a permanent action: worth a line that stands out
            "lead_deleted",
            actor=actor,
            workspace_id=self._workspace_id,
            company_id=company_id,
            domain=company.domain,
            status_was=company.status.value,
            contacts_removed=gone.contacts,
            messages_removed=gone.messages,
            events_removed=gone.events,
            drafts_deleted=deleted,
            drafts_left=len(left),
            domain_suppressed=also_suppress_domain,
        )
        return DeleteResult(
            company.domain, gone.contacts, gone.messages, deleted, left, also_suppress_domain
        )

    # ------------------------------------------------------------------ helpers

    def _log(
        self,
        action: str,
        actor: str,
        found: bool,
        cancelled: int,
        deleted: int,
        left: tuple[str, ...],
        **ids: str,
    ) -> None:
        emit = log.warning if left else log.info  # a draft we could not remove needs a person
        emit(
            "privacy_action",
            action=action,
            actor=actor,
            workspace_id=self._workspace_id,
            found=found,
            messages_cancelled=cancelled,
            drafts_deleted=deleted,
            drafts_left=len(left),
            **ids,
        )

    @staticmethod
    def _stop_everyone(uow: UnitOfWork, company_id: str, actor: str) -> tuple[int, list[DraftRef]]:
        cancelled, draft_ids = 0, []
        for contact in uow.contacts.for_company(company_id):
            count, drafts = stop_contact(uow, contact.id, actor)
            cancelled += count
            draft_ids += drafts
        return cancelled, draft_ids

    def _delete_drafts(self, drafts: tuple[DraftRef, ...]) -> tuple[int, tuple[str, ...]]:
        """Delete each draft from the mailbox holding it. Any that cannot be reached are
        returned, for the person to delete by hand."""
        deleted, left = 0, []
        for draft_id, mailbox_id in drafts:
            if self._mailboxes is None:
                left.append(draft_id)
                continue
            try:
                _, mailbox = self._mailboxes.open(mailbox_id)
                deleted += mailbox.delete_draft(draft_id) > 0
            except (ProviderError, MailboxUnavailable) as error:
                log.warning(
                    "draft_delete_failed", remote_draft_id=draft_id, reason=str(error)[:200]
                )
                left.append(draft_id)
        return deleted, tuple(left)
