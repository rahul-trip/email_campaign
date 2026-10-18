"""Looking at leads and doing the few things an operator does to one: edit, retry, release."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from outbound.db.models import EventRow, ProviderCallRow
from outbound.db.uow import UnitOfWork, UnitOfWorkFactory
from outbound.domain.actors import OPERATOR
from outbound.domain.entities import Company, Consent, Contact, ContactEmail, Message, Note
from outbound.domain.enums import (
    CompanyStatus,
    ConsentBasis,
    EntityType,
    HoldReason,
)
from outbound.domain.state_machines import (
    COMPANY,
    IllegalTransition,
    resume_status_for,
    retry_status_for,
)

EDITABLE = frozenset({"name", "country_code", "priority", "campaign_id"})


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
            target = resume_to or resume_status_for(company.hold_reason)
            if target is None:
                raise LeadError("this hold has no default: say which status to resume at")
            return self._move(uow, company, target, actor, "hold released")

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


def _entry(row: EventRow) -> TimelineEntry:
    return TimelineEntry(
        row.created_at, row.entity_type, row.entity_id, row.type, row.actor, dict(row.data)
    )


def _step(row: ProviderCallRow) -> WaterfallStep:
    return WaterfallStep(
        row.created_at,
        row.provider,
        row.operation,
        row.outcome.value,
        row.cost_micro_usd,
        row.latency_ms,
        row.contact_id,
    )
