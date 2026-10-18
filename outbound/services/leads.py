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
    CompanyStatus,
    ConsentBasis,
    ContactSource,
    ContactStatus,
    EntityType,
    HoldReason,
    Provenance,
)
from outbound.domain.errors import InvalidInput
from outbound.domain.names import split_name
from outbound.domain.policies import PolicyOutcome
from outbound.domain.state_machines import (
    COMPANY,
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
    def __init__(self, uow_factory: UnitOfWorkFactory, workspace_id: str) -> None:
        self._uow = uow_factory
        self._workspace_id = workspace_id

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
            return LeadDetail(
                company=uow.companies.get(company_id),
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
        actor: str = OPERATOR,
    ) -> Company:
        """Edit a saved target. A stale ``expected_version`` raises ``ConcurrencyConflict``."""
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

    def retry(self, company_id: str, *, actor: str = OPERATOR) -> Company:
        """Send a failed lead back to the stage that failed, without waiting out the back-off."""
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
        actor: str = OPERATOR,
    ) -> Company:
        """Let a held lead go on, at the stage that held it unless the operator chooses."""
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
        actor: str = OPERATOR,
    ) -> ContactWithEmails:
        """Add a person you know to a company already in the system, with their consent if given.

        The person is yours: ranked first and active, with the address (if any) marked as given
        by you. Consent is recorded in the same step, which is how a lead held for *consent
        required* gets the consent it is waiting for.
        """
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
            if address and uow.suppressions.blocks(address):
                raise InvalidInput("that address or its domain is on the do-not-contact list")
            if address and uow.emails.by_address(address) is not None:
                raise InvalidInput("that address already belongs to another person")
            contact = uow.contacts.add(
                company_id,
                rank=1,
                source=ContactSource.OPERATOR,
                full_name=name,
                first_name=first,
                last_name=last,
                title=(title or "").strip() or None,
                status=ContactStatus.ACTIVE,
                actor=actor,
            )
            emails = []
            if address:
                emails.append(
                    uow.emails.add(
                        contact.id, address, Provenance.OPERATOR_GIVEN, is_primary=True, actor=actor
                    )
                )
            if consent_basis is not None:
                uow.consents.add(contact.id, consent_basis, (consent_evidence or "").strip(), actor)
            uow.commit()
            return ContactWithEmails(contact, emails)

    def update_person(
        self,
        contact_id: str,
        *,
        full_name: str | None = None,
        title: str | None = None,
        email: str | None = None,
        actor: str = OPERATOR,
    ) -> ContactWithEmails:
        """Correct a person: their name or title, and an address if they have none yet.

        The values become yours (the engine will not overwrite them). A lead whose email step
        failed because the name was incomplete can then be retried.
        """
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
            if address and not any(e.email == address for e in held):
                if held:
                    raise InvalidInput("this person already has an address; it cannot be changed")
                if uow.suppressions.blocks(address):
                    raise InvalidInput("that address or its domain is on the do-not-contact list")
                if uow.emails.by_address(address) is not None:
                    raise InvalidInput("that address already belongs to another person")
                uow.emails.add(
                    contact_id, address, Provenance.OPERATOR_GIVEN, is_primary=True, actor=actor
                )
            uow.commit()
            return ContactWithEmails(updated, uow.emails.for_contact(contact_id))

    def requalify(self, company_id: str, *, actor: str = OPERATOR) -> Company:
        """Override a disqualification, such as a low fit score the operator disagrees with."""
        with self._uow(self._workspace_id) as uow:
            company = uow.companies.get(company_id)
            if company.status is not CompanyStatus.DISQUALIFIED:
                raise LeadError(f"the lead is {company.status.value}, not disqualified")
            return self._move(uow, company, CompanyStatus.QUALIFIED, actor, "operator override")

    def record_consent(
        self, contact_id: str, basis: ConsentBasis, evidence: str, *, actor: str = OPERATOR
    ) -> Consent:
        if not evidence.strip():
            raise LeadError("say where the consent came from: the evidence is kept with it")
        with self._uow(self._workspace_id) as uow:
            uow.contacts.get(contact_id)  # NotFound unless the person is in this workspace
            consent = uow.consents.add(contact_id, basis, evidence.strip(), actor)
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
