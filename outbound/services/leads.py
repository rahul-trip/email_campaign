"""Looking at leads and doing the few things an operator does to one: edit, retry, release."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from outbound.db.uow import UnitOfWork, UnitOfWorkFactory
from outbound.domain.actors import OPERATOR
from outbound.domain.entities import (
    Company,
    Consent,
    Contact,
    ContactEmail,
    Event,
    Message,
    Note,
    ProviderCall,
)
from outbound.domain.enums import (
    WORKABLE_CONTACT_STATUSES,
    CompanyStatus,
    ConsentBasis,
    ContactSource,
    ContactStatus,
    EntityType,
    HoldReason,
    MessageState,
    PolicyStage,
    Provenance,
)
from outbound.domain.errors import InvalidInput
from outbound.domain.names import same_person, split_name
from outbound.domain.policies import PolicyOutcome
from outbound.domain.state_machines import (
    COMPANY,
    POLICY_STAGE_AT,
    RESUME_AFTER_SKIP,
    IllegalTransition,
    resume_status_for,
    retry_status_for,
)
from outbound.services.journey import Journey, JourneyData, build_journey
from outbound.stages.policy import policy_decision_for

EDITABLE = frozenset({"name", "country_code", "priority", "campaign_id"})

# Holds that come from the country rule. Releasing one without changing what caused it only
# sends the lead back to the same check, which holds it again, so a release is refused first.
_POLICY_HOLDS = frozenset(
    {HoldReason.COUNTRY_UNKNOWN, HoldReason.CONSENT_REQUIRED, HoldReason.ENTITY_UNKNOWN}
)
# Past the point where any country check runs.
_AFTER_THE_MAILBOX = frozenset(
    {
        CompanyStatus.IN_SEQUENCE,
        CompanyStatus.REPLIED,
        CompanyStatus.COMPLETED,
        CompanyStatus.REJECTED,
        CompanyStatus.SUPPRESSED,
    }
)

# The reason on the event when the operator confirms a person a search could not place.
CONFIRMED_WORKS_HERE = "confirmed by the operator: works here"

# Where a lead can be when the operator picks someone else to write to: before the mailbox.
_RECIPIENT_CHANGEABLE = frozenset(
    {
        CompanyStatus.CONTACTS_FOUND,
        CompanyStatus.EMAIL_READY,
        CompanyStatus.COPY_READY,
        CompanyStatus.APPROVED,
        CompanyStatus.FAILED,
        CompanyStatus.HELD,
    }
)
_NEEDS_A_NAME = (
    "Give both a first and a last name, or the person's work email: the finder that looks up"
    " their address needs one or the other."
)
_HOW_TO_FIX = {
    HoldReason.COUNTRY_UNKNOWN: "Set the country under Edit this lead, then release it.",
    HoldReason.CONSENT_REQUIRED: (
        "Add the person who has consented under Add a person (tick that they have given consent),"
        " or change the country's rule under Settings, Country policies."
    ),
    HoldReason.ENTITY_UNKNOWN: (
        "Add a person who has consented under Add a person, or change the country's rule under"
        " Settings, Country policies."
    ),
}


class LeadError(Exception):
    """The action cannot be done to this lead; the message says why in plain words."""


@dataclass(frozen=True)
class ContactWithEmails:
    contact: Contact
    emails: list[ContactEmail]


@dataclass(frozen=True)
class LeadDetail:
    company: Company
    contacts: list[ContactWithEmails]
    messages: list[Message]
    notes: list[Note]
    # For a held lead: the stage whose country check held it (gate, contacts, email, copy or
    # deliver), so the screen offers to skip the rule from there or earlier.
    held_at: PolicyStage | None = None


@dataclass(frozen=True)
class TimelineEntry:
    at: datetime
    entity_type: EntityType
    entity_id: str
    type: str
    actor: str
    data: dict[str, Any]


@dataclass(frozen=True)
class WaterfallStep:
    at: datetime
    provider: str
    operation: str
    outcome: str
    cost_micro_usd: int
    latency_ms: int | None
    contact_id: str | None


class LeadService:
    def __init__(
        self, uow_factory: UnitOfWorkFactory, workspace_id: str, *, actor: str = OPERATOR
    ) -> None:
        self._uow = uow_factory
        self._workspace_id = workspace_id
        self._actor = actor

    def search(
        self,
        *,
        status: CompanyStatus | None = None,
        hold_reason: HoldReason | None = None,
        campaign_id: str | None = None,
        text: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Company], int]:
        with self._uow(self._workspace_id) as uow:
            return uow.companies.search(
                status=status,
                hold_reason=hold_reason,
                campaign_id=campaign_id,
                text=text,
                limit=limit,
                offset=offset,
            )

    def detail(self, company_id: str) -> LeadDetail:
        with self._uow(self._workspace_id) as uow:
            company = uow.companies.get(company_id)
            return LeadDetail(
                held_at=_held_at(uow, company),
                company=company,
                contacts=[
                    ContactWithEmails(c, uow.emails.for_contact(c.id))
                    for c in uow.contacts.for_company(company_id)
                ],
                messages=uow.messages.for_company(company_id),
                notes=uow.notes.for_company(company_id),
            )

    def timeline(self, company_id: str) -> list[TimelineEntry]:
        """Everything that happened to the lead, its people, addresses and messages."""
        with self._uow(self._workspace_id) as uow:
            uow.companies.get(company_id)  # NotFound for another workspace's lead
            entities: list[tuple[EntityType, str]] = [(EntityType.COMPANY, company_id)]
            for contact in uow.contacts.for_company(company_id):
                entities.append((EntityType.CONTACT, contact.id))
                entities += [
                    (EntityType.CONTACT_EMAIL, e.id) for e in uow.emails.for_contact(contact.id)
                ]
            entities += [(EntityType.MESSAGE, m.id) for m in uow.messages.for_company(company_id)]
            return [_entry(row) for row in uow.events.for_entities(entities)]

    def journey(self, company_id: str) -> Journey:
        """How the lead arrived and what happened at each stage."""
        with self._uow(self._workspace_id) as uow:
            company = uow.companies.get(company_id)
            people = [
                (c, uow.emails.for_contact(c.id)) for c in uow.contacts.for_company(company_id)
            ]
            messages = uow.messages.for_company(company_id)
            entities: list[tuple[EntityType, str]] = [(EntityType.COMPANY, company_id)]
            for contact, emails in people:
                entities.append((EntityType.CONTACT, contact.id))
                entities += [(EntityType.CONTACT_EMAIL, e.id) for e in emails]
            entities += [(EntityType.MESSAGE, m.id) for m in messages]
            return build_journey(
                JourneyData(
                    company=company,
                    campaign=uow.campaigns.get(company.campaign_id)
                    if company.campaign_id
                    else None,
                    origins=uow.imports.origins_for_company(company_id),
                    people=people,
                    messages=messages,
                    events=uow.events.for_entities(entities),
                    calls=uow.calls.for_company(company_id),
                )
            )

    def waterfall(self, company_id: str) -> list[WaterfallStep]:
        with self._uow(self._workspace_id) as uow:
            uow.companies.get(company_id)
            return [_step(row) for row in uow.calls.for_company(company_id)]

    def update(
        self,
        company_id: str,
        changes: Mapping[str, Any],
        *,
        expected_version: int,
        actor: str | None = None,
    ) -> Company:
        """Edit a saved target. A stale ``expected_version`` raises ``ConcurrencyConflict``."""
        actor = actor or self._actor
        unknown = set(changes) - EDITABLE
        if unknown:
            raise LeadError(f"cannot change {sorted(unknown)}")
        with self._uow(self._workspace_id) as uow:
            if changes.get("campaign_id"):
                uow.campaigns.get(str(changes["campaign_id"]))  # must be one of ours
            updated = uow.companies.update_fields(
                company_id, changes, actor=actor, expected_version=expected_version
            )
            uow.commit()
            return updated

    def retry(self, company_id: str, *, actor: str | None = None) -> Company:
        """Send a failed lead back to the stage that failed, without waiting out the back-off."""
        actor = actor or self._actor
        with self._uow(self._workspace_id) as uow:
            company = uow.companies.get(company_id)
            if company.status is not CompanyStatus.FAILED or company.failed_stage is None:
                raise LeadError(f"the lead is {company.status.value}, not failed")
            updated = uow.companies.transition(
                company_id,
                retry_status_for(company.failed_stage),
                expected_version=company.row_version,
                actor=actor,
                reason=f"retry after {company.failed_stage} failed",
                next_action_at=None,
            )
            uow.commit()
            return updated

    def release_hold(
        self,
        company_id: str,
        *,
        resume_to: CompanyStatus | None = None,
        actor: str | None = None,
    ) -> Company:
        """Let a held lead go on, at the stage that held it unless the operator chooses."""
        actor = actor or self._actor
        with self._uow(self._workspace_id) as uow:
            company = uow.companies.get(company_id)
            if company.status is not CompanyStatus.HELD or company.hold_reason is None:
                raise LeadError(f"the lead is {company.status.value}, not held")
            if company.hold_reason in _POLICY_HOLDS:
                self._refuse_if_nothing_changed(uow, company)
            target = resume_to or resume_status_for(company.hold_reason)
            if target is None:
                raise LeadError("this hold has no default: say which status to resume at")
            return self._move(uow, company, target, actor, "hold released")

    @staticmethod
    def _refuse_if_nothing_changed(uow: UnitOfWork, company: Company) -> None:
        decision = policy_decision_for(uow, company)
        if decision.outcome is PolicyOutcome.ALLOW:
            return
        if decision.outcome is PolicyOutcome.BLOCK or decision.hold_reason == company.hold_reason:
            why = "; ".join(decision.reasons) or "the country rule"
            fix = _HOW_TO_FIX.get(company.hold_reason or HoldReason.NEEDS_OPERATOR, "")
            raise LeadError(
                f"Nothing has changed since it was held ({why}), so releasing it would only hold"
                f" it again. {fix}".strip()
            )

    def add_person(
        self,
        company_id: str,
        *,
        full_name: str,
        title: str | None = None,
        email: str | None = None,
        consent_basis: ConsentBasis | None = None,
        consent_evidence: str | None = None,
        actor: str | None = None,
    ) -> ContactWithEmails:
        """Add a person you know to a company already in the system, with their consent if given.

        The person is yours: ranked first and active, with the address (if any) marked as given
        by you. Consent is recorded in the same step, which is how a lead held for *consent
        required* gets the consent it is waiting for.
        """
        actor = actor or self._actor
        name = " ".join(full_name.split())
        if not name:
            raise InvalidInput("give the person's name")
        address = _clean_address(email)
        first, last = split_name(name)
        if not address and not (first and last):
            raise InvalidInput(_NEEDS_A_NAME)
        if consent_basis is not None and not (consent_evidence or "").strip():
            raise InvalidInput("say where the consent came from: the evidence is kept with it")
        with self._uow(self._workspace_id) as uow:
            uow.companies.get(company_id)  # NotFound for another workspace's lead
            existing = next(
                (
                    c
                    for c in uow.contacts.for_company(company_id)
                    if c.status in WORKABLE_CONTACT_STATUSES and same_person(c.full_name, name)
                ),
                None,
            )
            if existing is not None:
                # The same person again (often first added by first name only): give them the
                # new details instead of a second card that splits their history.
                changes: dict[str, Any] = {}
                if len(name.split()) > len((existing.full_name or "").split()):
                    changes.update(full_name=name, first_name=first, last_name=last)
                if title and title.strip():
                    changes["title"] = title.strip()
                if changes:
                    uow.contacts.update_fields(existing.id, changes, actor=actor)
                contact_id = existing.id
            else:
                contact_id = uow.contacts.add(
                    company_id,
                    rank=1,
                    source=ContactSource.OPERATOR,
                    full_name=name,
                    first_name=first,
                    last_name=last,
                    title=(title or "").strip() or None,
                    status=ContactStatus.ACTIVE,
                    actor=actor,
                ).id
            if address:
                _give_address(uow, contact_id, address, actor)
            if consent_basis is not None:
                uow.consents.add(contact_id, consent_basis, (consent_evidence or "").strip(), actor)
            uow.contacts.make_first(contact_id)
            uow.commit()
            return ContactWithEmails(
                uow.contacts.get(contact_id), uow.emails.for_contact(contact_id)
            )

    def update_person(
        self,
        contact_id: str,
        *,
        full_name: str | None = None,
        title: str | None = None,
        email: str | None = None,
        actor: str | None = None,
    ) -> ContactWithEmails:
        """Correct a person: their name, title or address.

        The values become yours (the engine will not overwrite them). A new address becomes the
        one written to, the earlier one stays as history, and the person is put first. A lead
        whose email step failed (a wrong guess, an incomplete name) can then be retried.
        """
        actor = actor or self._actor
        address = _clean_address(email)
        with self._uow(self._workspace_id) as uow:
            contact = uow.contacts.get(contact_id)  # NotFound for another workspace's person
            held = uow.emails.for_contact(contact_id)
            name = " ".join(
                (full_name if full_name is not None else contact.full_name or "").split()
            )
            first, last = split_name(name)
            if not name:
                raise InvalidInput("give the person's name")
            if not (held or address) and not (first and last):
                raise InvalidInput(_NEEDS_A_NAME)
            changes: dict[str, Any] = {"full_name": name, "first_name": first, "last_name": last}
            if title is not None:
                changes["title"] = title.strip() or None
            updated = uow.contacts.update_fields(contact_id, changes, actor=actor)
            if address:
                _give_address(uow, contact_id, address, actor)
                uow.contacts.make_first(contact_id)
            uow.commit()
            return ContactWithEmails(
                uow.contacts.get(updated.id), uow.emails.for_contact(contact_id)
            )

    def confirm_person(self, contact_id: str, *, actor: str | None = None) -> ContactWithEmails:
        """Say that a person a search could not place here does work here.

        Until then they are never looked up or written to. The confirmation is recorded with
        your name, and approving an email to them asks you to acknowledge it.
        """
        actor = actor or self._actor
        with self._uow(self._workspace_id) as uow:
            contact = uow.contacts.get(
                contact_id
            )  # NotFound unless the person is in this workspace
            if contact.status is not ContactStatus.UNCONFIRMED:
                raise LeadError(
                    f"this person is {contact.status.value}, not waiting to be confirmed"
                )
            confirmed = uow.contacts.transition(
                contact_id, ContactStatus.CANDIDATE, actor=actor, reason=CONFIRMED_WORKS_HERE
            )
            uow.commit()
            return ContactWithEmails(confirmed, uow.emails.for_contact(contact_id))

    def remove_person(self, contact_id: str, *, actor: str | None = None) -> None:
        """Take a person off a lead, such as someone a search matched by mistake.

        Refused once anything has been written to them: then the history matters, and the
        person can be suppressed or forgotten instead.
        """
        actor = actor or self._actor
        with self._uow(self._workspace_id) as uow:
            uow.contacts.get(contact_id)  # NotFound unless the person is in this workspace
            if uow.messages.for_contact(contact_id):
                raise LeadError(
                    "An email has already been written to this person, so they stay on the lead."
                    " Suppress them instead if they must not be contacted."
                )
            uow.erasure.delete_contact(contact_id, actor=actor)
            uow.commit()

    def change_recipient(
        self, company_id: str, contact_id: str, *, actor: str | None = None
    ) -> Company:
        """Write to a different person at this lead.

        An email waiting for review (or approved but not yet in the mailbox) is cancelled, the
        person is put first, and the lead goes back to the email step, which reuses an address
        it already has at no cost.
        """
        actor = actor or self._actor
        with self._uow(self._workspace_id) as uow:
            company = uow.companies.get(company_id)
            contact = uow.contacts.get(contact_id)
            if contact.company_id != company_id:
                raise LeadError("that person is not at this lead")
            if contact.status not in WORKABLE_CONTACT_STATUSES:
                raise LeadError(f"that person is {contact.status.value} and cannot be written to")
            if company.status not in _RECIPIENT_CHANGEABLE:
                raise LeadError(
                    f"the lead is {company.status.value}: the person can only be changed before"
                    " the email is in the mailbox"
                )
            for message in uow.messages.for_company(company_id):
                if message.state in (MessageState.GENERATED, MessageState.APPROVED):
                    uow.messages.transition(
                        message.id,
                        MessageState.CANCELLED,
                        expected_version=message.row_version,
                        actor=actor,
                    )
            uow.contacts.make_first(contact_id)
            if company.status is CompanyStatus.CONTACTS_FOUND:
                uow.commit()
                return uow.companies.get(company_id)
            return self._move(
                uow, company, CompanyStatus.CONTACTS_FOUND, actor, "recipient changed"
            )

    def skip_policy(
        self, company_id: str, from_stage: PolicyStage, reason: str, *, actor: str | None = None
    ) -> Company:
        """Skip the country rule for this lead from ``from_stage`` onward.

        Suppression still applies, and the footer follows the workspace setting. A lead held
        (or disqualified) by the rule at that stage or a later one goes straight on from where
        it was stopped; otherwise the skip simply waits until the lead gets there.
        """
        actor = actor or self._actor
        why = " ".join(reason.split())
        if not why:
            raise InvalidInput("say why the country rule is skipped: it is kept with the record")
        with self._uow(self._workspace_id) as uow:
            company = uow.companies.get(company_id)
            if company.status in _AFTER_THE_MAILBOX:
                raise LeadError(f"the lead is {company.status.value}: nothing is left to check")
            stopped_at = _stopped_by_policy_at(uow, company)
            order = list(PolicyStage)
            if stopped_at is not None and order.index(from_stage) > order.index(stopped_at):
                raise LeadError(
                    f"The country rule stopped this lead at the {stopped_at.value} step, so the"
                    f" skip must start there or earlier, not at {from_stage.value}."
                )
            uow.companies.update_fields(
                company_id,
                {"policy_skip_from": from_stage},
                actor=actor,
                expected_version=company.row_version,
            )
            uow.events.append(
                EntityType.COMPANY,
                company_id,
                "policy_skip_granted",
                actor,
                {"from_stage": from_stage.value, "reason": why},
            )
            company = uow.companies.get(company_id)
            if stopped_at is None:
                uow.commit()
                return company
            if company.status is CompanyStatus.DISQUALIFIED:
                target = CompanyStatus.QUALIFIED
            else:
                target = RESUME_AFTER_SKIP[stopped_at]
            return self._move(uow, company, target, actor, "country rule skipped by the operator")

    def revoke_policy_skip(self, company_id: str, *, actor: str | None = None) -> Company:
        """Apply the country rule to this lead again. Refused once its email is approved."""
        actor = actor or self._actor
        with self._uow(self._workspace_id) as uow:
            company = uow.companies.get(company_id)
            if company.policy_skip_from is None:
                raise LeadError("the country rule is not skipped for this lead")
            if company.status is CompanyStatus.APPROVED or company.status in _AFTER_THE_MAILBOX:
                raise LeadError(
                    "The email was approved with the country rule skipped. Reject it first if"
                    " the rule should apply."
                )
            updated = uow.companies.update_fields(
                company_id,
                {"policy_skip_from": None},
                actor=actor,
                expected_version=company.row_version,
            )
            uow.events.append(EntityType.COMPANY, company_id, "policy_skip_revoked", actor, {})
            uow.commit()
            return updated

    def release_policy_holds(self, *, actor: str | None = None) -> int:
        """Release every lead held by a country rule that no longer holds it (say, after the
        rules were switched off for the workspace). Returns how many went on."""
        actor = actor or self._actor
        released = 0
        with self._uow(self._workspace_id) as uow:
            held, _ = uow.companies.search(status=CompanyStatus.HELD, limit=10_000)
            for company in held:
                stopped_at = _stopped_by_policy_at(uow, company)
                if stopped_at is None:
                    continue
                decision = policy_decision_for(uow, company, stage=stopped_at.value)
                if decision.outcome is not PolicyOutcome.ALLOW:
                    continue
                uow.companies.transition(
                    company.id,
                    RESUME_AFTER_SKIP[stopped_at],
                    expected_version=company.row_version,
                    actor=actor,
                    reason="country rule no longer holds it",
                    next_action_at=None,
                )
                released += 1
            uow.commit()
        return released

    def skip_email_verification(
        self, email_id: str, reason: str, *, actor: str | None = None
    ) -> ContactWithEmails:
        """Write to this address whatever the verifier said (even *invalid*), or before it is
        checked. The address becomes the one written to and its person is put first; a lead
        stopped at the email step goes on to writing. Approving the email asks you to confirm.
        """
        actor = actor or self._actor
        why = " ".join(reason.split())
        if not why:
            raise InvalidInput("say why the check is skipped: it is kept with the record")
        with self._uow(self._workspace_id) as uow:
            address = uow.emails.get(email_id)  # NotFound unless it is in this workspace
            contact = uow.contacts.get(address.contact_id)
            if not address.email:
                raise LeadError("this address was erased")
            if uow.suppressions.blocks(address.email):
                raise LeadError("that address or its domain is on the do-not-contact list")
            if contact.status not in WORKABLE_CONTACT_STATUSES:
                raise LeadError(
                    f"this person is {contact.status.value}: confirm them first"
                    if contact.status is ContactStatus.UNCONFIRMED
                    else f"this person is {contact.status.value} and cannot be written to"
                )
            uow.emails.set_verification_skipped(email_id, True, actor=actor, reason=why)
            uow.emails.set_primary(email_id)
            uow.contacts.make_first(contact.id)
            company = uow.companies.get(contact.company_id)
            if _stopped_at_email(company):
                uow.companies.transition(
                    company.id,
                    CompanyStatus.CONTACTS_FOUND,
                    expected_version=company.row_version,
                    actor=actor,
                    reason="email check skipped by the operator",
                    next_action_at=None,
                )
            uow.commit()
            return ContactWithEmails(
                uow.contacts.get(contact.id), uow.emails.for_contact(contact.id)
            )

    def restore_email_verification(
        self, email_id: str, *, actor: str | None = None
    ) -> ContactWithEmails:
        """Check this address again like any other. Refused once its email is approved."""
        actor = actor or self._actor
        with self._uow(self._workspace_id) as uow:
            address = uow.emails.get(email_id)
            approved = [
                m
                for m in uow.messages.for_contact(address.contact_id)
                if m.contact_email_id == email_id
                and m.state
                not in (MessageState.GENERATED, MessageState.CANCELLED, MessageState.REJECTED)
            ]
            if approved:
                raise LeadError(
                    "An email to this address was approved with the check skipped. Reject it"
                    " first if it should be checked."
                )
            uow.emails.set_verification_skipped(email_id, False, actor=actor)
            uow.commit()
            return ContactWithEmails(
                uow.contacts.get(address.contact_id), uow.emails.for_contact(address.contact_id)
            )

    def research_again(self, company_id: str, *, actor: str | None = None) -> Company:
        """Send a lead back to research, to pick up fresh news or a changed site.

        Everything after research runs again too: the gate, people, the email (addresses already
        found are reused at no cost) and the copy. An email waiting for review or approved but
        not yet in the mailbox is cancelled, so the new one replaces it. What you set by hand
        (name, country, people, addresses, consent) is kept.
        """
        actor = actor or self._actor
        with self._uow(self._workspace_id) as uow:
            company = uow.companies.get(company_id)
            if company.status is CompanyStatus.NEW:
                raise LeadError("the lead has not been researched yet: the next run does it")
            if company.status in _AFTER_THE_MAILBOX:
                raise LeadError(
                    f"the lead is {company.status.value}: its email has already left, so it is"
                    " not researched again"
                )
            for message in uow.messages.for_company(company_id):
                if message.state in (MessageState.GENERATED, MessageState.APPROVED):
                    uow.messages.transition(
                        message.id,
                        MessageState.CANCELLED,
                        expected_version=message.row_version,
                        actor=actor,
                    )
            return self._move(uow, company, CompanyStatus.NEW, actor, "research again")

    def requalify(self, company_id: str, *, actor: str | None = None) -> Company:
        """Override a disqualification, such as a low fit score the operator disagrees with."""
        actor = actor or self._actor
        with self._uow(self._workspace_id) as uow:
            company = uow.companies.get(company_id)
            if company.status is not CompanyStatus.DISQUALIFIED:
                raise LeadError(f"the lead is {company.status.value}, not disqualified")
            return self._move(uow, company, CompanyStatus.QUALIFIED, actor, "operator override")

    def record_consent(
        self, contact_id: str, basis: ConsentBasis, evidence: str, *, actor: str | None = None
    ) -> Consent:
        actor = actor or self._actor
        if not evidence.strip():
            raise LeadError("say where the consent came from: the evidence is kept with it")
        with self._uow(self._workspace_id) as uow:
            uow.contacts.get(contact_id)  # NotFound unless the person is in this workspace
            consent = uow.consents.add(contact_id, basis, evidence.strip(), actor)
            uow.contacts.make_first(contact_id)  # the person who consented is the one to write to
            uow.commit()
            return consent

    @staticmethod
    def _move(
        uow: UnitOfWork, company: Company, target: CompanyStatus, actor: str, reason: str
    ) -> Company:
        try:
            COMPANY.check(company.status, target)
        except IllegalTransition as error:
            raise LeadError(str(error)) from None
        updated = uow.companies.transition(
            company.id,
            target,
            expected_version=company.row_version,
            actor=actor,
            reason=reason,
            next_action_at=None,
        )
        uow.commit()
        return updated


def _held_at(uow: UnitOfWork, company: Company) -> PolicyStage | None:
    """The stage that put a held lead on hold, read from the event that did it."""
    if company.status is not CompanyStatus.HELD:
        return None
    events = uow.events.for_entities([(EntityType.COMPANY, company.id)])
    for event in reversed(events):
        if event.type == "status_changed" and event.data.get("to") == CompanyStatus.HELD.value:
            return POLICY_STAGE_AT.get(CompanyStatus(event.data["from"]))
    return None


def _stopped_by_policy_at(uow: UnitOfWork, company: Company) -> PolicyStage | None:
    """Where the country rule stopped this lead, if it did: a hold, or a block at the gate."""
    if company.status is CompanyStatus.DISQUALIFIED:
        blocked = (company.policy_decision or {}).get("outcome") == PolicyOutcome.BLOCK.value
        return PolicyStage.GATE if blocked else None
    if company.status is not CompanyStatus.HELD:
        return None
    if company.hold_reason not in _POLICY_HOLDS | {HoldReason.NEEDS_OPERATOR}:
        return None  # a catch-all hold is about the address, not the country
    return _held_at(uow, company)


def _stopped_at_email(company: Company) -> bool:
    """A lead the email step failed, or held over an unproven catch-all address."""
    if company.status is CompanyStatus.FAILED:
        return company.failed_stage == "email"
    return company.status is CompanyStatus.HELD and company.hold_reason in (
        HoldReason.CATCH_ALL_UNVERIFIED,
        HoldReason.CATCH_ALL_RESOLVING,
    )


def _give_address(uow: UnitOfWork, contact_id: str, address: str, actor: str) -> None:
    """Make ``address`` the person's primary one; earlier addresses stay as history."""
    held = uow.emails.by_address(address)
    if held is not None:
        if held.contact_id != contact_id:
            raise InvalidInput("that address already belongs to another person")
        uow.emails.set_primary(held.id)
        return
    if uow.suppressions.blocks(address):
        raise InvalidInput("that address or its domain is on the do-not-contact list")
    uow.emails.add(contact_id, address, Provenance.OPERATOR_GIVEN, is_primary=True, actor=actor)


def _clean_address(email: str | None) -> str | None:
    address = (email or "").strip().lower() or None
    if address and ("@" not in address or " " in address):
        raise InvalidInput(f"{email!r} is not an email address")
    return address


def _entry(row: Event) -> TimelineEntry:
    return TimelineEntry(
        row.created_at, row.entity_type, row.entity_id, row.type, row.actor, dict(row.data)
    )


def _step(row: ProviderCall) -> WaterfallStep:
    return WaterfallStep(
        row.created_at,
        row.provider,
        row.operation,
        row.outcome.value,
        row.cost_micro_usd,
        row.latency_ms,
        row.contact_id,
    )
