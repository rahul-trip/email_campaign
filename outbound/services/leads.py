"""Looking at leads and doing the few things an operator does to one: edit, retry, release."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from outbound.db.errors import NotFound
from outbound.db.types import utcnow
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
    CompanySource,
    CompanyStatus,
    ConsentBasis,
    ContactSource,
    ContactStatus,
    EmailStatus,
    EntityType,
    HoldReason,
    MessageState,
    PolicyStage,
    Provenance,
    UsageStep,
)
from outbound.domain.errors import InvalidInput
from outbound.domain.names import read_profile_title, same_person, search_name, split_name
from outbound.domain.placement import Placement, place_by_rules
from outbound.domain.policies import PolicyOutcome
from outbound.domain.state_machines import (
    COMPANY,
    CONTACT,
    POLICY_STAGE_AT,
    RESUME_AFTER_SKIP,
    IllegalTransition,
    resume_status_for,
    retry_status_for,
)
from outbound.metering.metered import call_scope
from outbound.metering.quota import credit_left
from outbound.providers.errors import ProviderError
from outbound.providers.ports import LlmClient, SearchProvider
from outbound.services.journey import Journey, JourneyData, build_journey
from outbound.stages.policy import policy_decision_for
from outbound.stages.research.employment import Candidate, judge_people
from outbound.stages.research.graph import search_people
from outbound.stages.research.linkedin import NAMES_PER_SEARCH, find_linkedin, profile_address
from outbound.stages.research.stage import save_people

EDITABLE = frozenset({"name", "country_code", "priority", "campaign_id"})

# Holds that come from the country rule. Releasing one without changing what caused it only
# sends the lead back to the same check, which holds it again, so a release is refused first.
_POLICY_HOLDS = frozenset(
    {HoldReason.COUNTRY_UNKNOWN, HoldReason.CONSENT_REQUIRED, HoldReason.ENTITY_UNKNOWN}
)
# Holds that need no fix per lead, so many can be released with one press: the operator's own
# choice to wait (a LinkedIn message was sent). The country and consent holds need a fix first.
_BULK_RELEASABLE = frozenset({HoldReason.LINKEDIN_CONTACTED})
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
class PeopleFound:
    """What "Find people again" did."""

    found: int
    added: int
    works_here: int
    unsure: int
    retried: bool


@dataclass(frozen=True)
class PeopleCheck:
    """What "Check who works here" found out about a lead's people."""

    checked: int
    works_here: int
    not_here: int
    unsure: int


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
    credits_milli: int  # AI credits, in thousandths
    latency_ms: int | None
    contact_id: str | None
    asked: str = ""  # what the call asked, in words ("" for calls made before this was kept)
    got: str = ""


class LeadService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        workspace_id: str,
        *,
        actor: str = OPERATOR,
        search: SearchProvider | None = None,
        llm: LlmClient | None = None,
    ) -> None:
        self._uow = uow_factory
        self._workspace_id = workspace_id
        self._actor = actor
        self._search = search  # behind the meter; finds a person's LinkedIn profile
        self._llm = llm  # behind the meter; settles who works at the company

    def search(
        self,
        *,
        status: CompanyStatus | None = None,
        hold_reason: HoldReason | None = None,
        campaign_id: str | None = None,
        text: str | None = None,
        waiting_for_credits: bool | None = None,
        min_fit: int | None = None,
        hot: bool | None = None,
        source: CompanySource | None = None,
        country: str | None = None,
        sort: str = "newest",
        direction: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Company], int]:
        with self._uow(self._workspace_id) as uow:
            return uow.companies.search(
                status=status,
                hold_reason=hold_reason,
                campaign_id=campaign_id,
                text=text,
                waiting_for_credits=waiting_for_credits,
                min_fit=min_fit,
                hot=hot,
                source=source,
                country=country,
                sort=sort,
                direction=direction,
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

    def find_linkedin(self, contact_id: str, *, actor: str | None = None) -> str | None:
        """Look for this person's LinkedIn profile with one search. The address is kept only
        when the profile's headline names the same person; None when nothing clearly fits."""
        actor = actor or self._actor
        if self._search is None:
            raise LeadError(
                "searching is not set up (no Tavily key), so LinkedIn cannot be looked up"
            )
        with self._uow(self._workspace_id) as uow:
            contact = uow.contacts.get(contact_id)
            company = uow.companies.get(contact.company_id)
        if not contact.full_name:
            raise LeadError("this person has no name yet, so there is nothing to search for")
        with call_scope(company_id=company.id, contact_id=contact_id):
            link = find_linkedin(
                self._search, contact.full_name, company.name or "", company.domain
            )
        if link is None:
            return None
        with self._uow(self._workspace_id) as uow:
            if uow.contacts.linkedin_taken(link):
                return None  # another person on this workspace already has that profile
            uow.contacts.update_fields(contact_id, {"linkedin_url": link}, actor=actor)
            uow.commit()
        return link

    def find_people_again(self, company_id: str, *, actor: str | None = None) -> PeopleFound:
        """Search again for people who decide at this lead, by the campaign's job titles (or
        founder, CEO and CTO without a campaign). Up to two searches and one model call.

        New people are added as research adds them: placed at the company, or unconfirmed for
        you to check; nobody already at the lead is touched. A lead that had failed because
        nobody could be written to goes back to the people step.
        """
        actor = actor or self._actor
        if self._search is None:
            raise LeadError("searching is not set up (no Tavily key), so people cannot be found")
        with self._uow(self._workspace_id) as uow:
            company = uow.companies.get(company_id)
            campaign = uow.campaigns.get(company.campaign_id) if company.campaign_id else None
        titles = [*(campaign.target_titles if campaign else ())] or list(_FOUNDER_TITLES)
        name = search_name(company.name or "") or company.name or company.domain
        site_text = str((company.research or {}).get("summary") or "")
        with call_scope(company_id=company_id):
            people = search_people(self._search, name, company.domain, titles, site_text)
            # The same profile can come back from both searches: once each.
            people = list({p.linkedin_url or p.name.lower(): p for p in people}.values())
            open_ = [i for i, p in enumerate(people) if p.placement is Placement.UNSURE]
            if open_ and self._llm is not None:
                verdicts = judge_people(
                    self._llm,
                    name,
                    company.domain,
                    site_text,
                    [Candidate(people[i].name, people[i].evidence) for i in open_],
                )
                for i, (placement, reason) in zip(open_, verdicts, strict=True):
                    people[i] = replace(people[i], placement=placement, reason=reason)
        kept = tuple(p for p in people if p.placement is not Placement.NOT_HERE)
        with self._uow(self._workspace_id) as uow:
            before = {c.full_name for c in uow.contacts.for_company(company_id)}
            added = save_people(uow, company_id, kept)
            fresh = [c for c in uow.contacts.for_company(company_id) if c.full_name not in before]
            company = uow.companies.get(company_id)
            # The people step (or the email step, which writes only to someone who decides) failed
            # for want of a person: with someone new to write to, it runs again.
            retried = (
                company.status is CompanyStatus.FAILED
                and company.failed_stage in ("contacts", "email")
                and any(c.status in WORKABLE_CONTACT_STATUSES for c in fresh)
            )
            if retried and company.failed_stage:
                self._move(
                    uow,
                    company,
                    retry_status_for(company.failed_stage),
                    actor,
                    "people found again",
                )
            uow.commit()
        return PeopleFound(
            found=len(people),
            added=added,
            works_here=sum(c.status in WORKABLE_CONTACT_STATUSES for c in fresh),
            unsure=sum(c.status is ContactStatus.UNCONFIRMED for c in fresh),
            retried=retried,
        )

    def retry_email(self, contact_id: str, *, actor: str | None = None) -> Company:
        """Look for this person's email again, with fresh vendor answers, on the next run.

        Allowed while no email has been written to the lead: it is failed at the email step, or
        waiting at, or just past, it. Later on, use *Write to this person instead*."""
        actor = actor or self._actor
        with self._uow(self._workspace_id) as uow:
            contact = uow.contacts.get(contact_id)
            if contact.status not in WORKABLE_CONTACT_STATUSES:
                raise LeadError("this person cannot be worked on any more")
            updated = self._ask_again(uow, contact, actor)
            uow.commit()
            return updated

    def retry_email_for_companies(
        self, company_ids: list[str], *, actor: str | None = None
    ) -> tuple[int, int]:
        """Look again for the email of each lead held on a catch-all address.

        For each lead the people whose address is a catch-all are asked again (else the
        first-ranked workable person). A lead in any other state is skipped, not refused, so one
        stale row on a screen does not stop the rest. Returns (asked, skipped)."""
        actor = actor or self._actor
        asked = skipped = 0
        with self._uow(self._workspace_id) as uow:
            for company_id in dict.fromkeys(company_ids):
                try:
                    company = uow.companies.get(company_id)
                except NotFound:
                    skipped += 1
                    continue
                if company.status is not CompanyStatus.HELD or company.hold_reason not in (
                    HoldReason.CATCH_ALL_UNVERIFIED,
                    HoldReason.CATCH_ALL_RESOLVING,
                ):
                    skipped += 1
                    continue
                people = [
                    c
                    for c in uow.contacts.for_company(company_id)
                    if c.status in WORKABLE_CONTACT_STATUSES
                ]
                catch_all = {
                    EmailStatus.CATCH_ALL_PENDING,
                    EmailStatus.CATCH_ALL_UNVERIFIED,
                }
                chosen = [
                    c
                    for c in people
                    if any(e.status in catch_all for e in uow.emails.for_contact(c.id))
                ] or people[:1]
                if not chosen:
                    skipped += 1
                    continue
                for contact in chosen:
                    self._ask_again(uow, contact, actor)
                asked += 1
            uow.commit()
        return asked, skipped

    @staticmethod
    def _ask_again(uow: UnitOfWork, contact: Contact, actor: str) -> Company:
        """Mark one person for a fresh email search and move their lead back to that step."""
        company = uow.companies.get(contact.company_id)
        if (
            (company.status is CompanyStatus.FAILED and company.failed_stage == "email")
            or company.status is CompanyStatus.EMAIL_READY
            or (
                company.status is CompanyStatus.HELD
                and company.hold_reason
                in (HoldReason.CATCH_ALL_UNVERIFIED, HoldReason.CATCH_ALL_RESOLVING)
            )
        ):
            updated = uow.companies.transition(
                company.id,
                CompanyStatus.CONTACTS_FOUND,
                expected_version=company.row_version,
                actor=actor,
                reason="email search asked for again",
                next_action_at=None,
            )
        elif company.status is CompanyStatus.CONTACTS_FOUND:
            updated = company
        else:
            raise LeadError(
                f"the lead is {company.status.value}: its email is past the search. "
                "Use Write to this person instead."
            )
        uow.contacts.set_refresh_email(contact.id, True)
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

    def retry_many(self, company_ids: list[str], *, actor: str | None = None) -> tuple[int, int]:
        """Send each failed lead back to the stage that failed, in one transaction.

        A lead that is not failed any more (it retried itself, or someone else acted) is skipped,
        not refused, so one stale row on a screen does not stop the rest. Returns
        (retried, skipped)."""
        actor = actor or self._actor
        retried = skipped = 0
        with self._uow(self._workspace_id) as uow:
            for company_id in dict.fromkeys(company_ids):
                try:
                    company = uow.companies.get(company_id)
                except NotFound:
                    skipped += 1
                    continue
                if company.status is not CompanyStatus.FAILED or company.failed_stage is None:
                    skipped += 1
                    continue
                uow.companies.transition(
                    company_id,
                    retry_status_for(company.failed_stage),
                    expected_version=company.row_version,
                    actor=actor,
                    reason=f"retry after {company.failed_stage} failed",
                    next_action_at=None,
                )
                retried += 1
            uow.commit()
        return retried, skipped

    def release_many(self, company_ids: list[str], *, actor: str | None = None) -> tuple[int, int]:
        """Release each lead held for a reason that needs no fix per lead (``_BULK_RELEASABLE``),
        to where that hold resumes. Anything else is skipped. Returns (released, skipped)."""
        actor = actor or self._actor
        released = skipped = 0
        with self._uow(self._workspace_id) as uow:
            for company_id in dict.fromkeys(company_ids):
                try:
                    company = uow.companies.get(company_id)
                except NotFound:
                    skipped += 1
                    continue
                target = (
                    resume_status_for(company.hold_reason)
                    if company.status is CompanyStatus.HELD
                    and company.hold_reason in _BULK_RELEASABLE
                    else None
                )
                if target is None:
                    skipped += 1
                    continue
                uow.companies.transition(
                    company_id,
                    target,
                    expected_version=company.row_version,
                    actor=actor,
                    reason="hold released",
                    next_action_at=None,
                )
                released += 1
            uow.commit()
        return released, skipped

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
        linkedin_url: str | None = None,
        actor: str | None = None,
    ) -> ContactWithEmails:
        """Correct a person: their name, title, address or LinkedIn profile.

        ``linkedin_url`` sets the profile (any LinkedIn profile link, made plain) or, given as
        ``""``, removes it; left out, it is not touched.

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
            if linkedin_url is not None:
                changes["linkedin_url"] = _clean_profile(uow, contact_id, linkedin_url)
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
        your name, and approving an email to them asks you to acknowledge it. Also undoes a
        person being set aside as not working here.
        """
        actor = actor or self._actor
        with self._uow(self._workspace_id) as uow:
            contact = uow.contacts.get(
                contact_id
            )  # NotFound unless the person is in this workspace
            if contact.status not in (ContactStatus.UNCONFIRMED, ContactStatus.NOT_HERE):
                raise LeadError(
                    f"this person is {contact.status.value}, not waiting to be confirmed"
                )
            confirmed = uow.contacts.transition(
                contact_id, ContactStatus.CANDIDATE, actor=actor, reason=CONFIRMED_WORKS_HERE
            )
            uow.commit()
            return ContactWithEmails(confirmed, uow.emails.for_contact(contact_id))

    def mark_not_here(
        self, contact_id: str, *, actor: str | None = None, note: str = ""
    ) -> ContactWithEmails:
        """Say that a person does not work at this lead (a namesake, or they moved on).

        They stay on the lead, greyed out, so a new search does not find them again; they are
        never looked up or written to. Refused once an email was written to them.
        """
        actor = actor or self._actor
        why = " ".join(note.split()) or "marked by the operator: does not work here"
        with self._uow(self._workspace_id) as uow:
            contact = uow.contacts.get(contact_id)
            if uow.messages.for_contact(contact_id):
                raise LeadError(
                    "An email has already been written to this person, so they stay on the lead."
                    " Suppress them instead if they must not be contacted."
                )
            if not CONTACT.allows(contact.status, ContactStatus.NOT_HERE):
                raise LeadError(f"this person is {contact.status.value}")
            moved = uow.contacts.transition(
                contact_id,
                ContactStatus.NOT_HERE,
                actor=actor,
                reason="marked by the operator: does not work here",
                placement_note=why,
            )
            self._drop_recipient(uow, contact.company_id, actor)
            uow.commit()
            return ContactWithEmails(moved, uow.emails.for_contact(contact_id))

    @staticmethod
    def _drop_recipient(uow: UnitOfWork, company_id: str, actor: str) -> None:
        """A lead waiting at the copy step goes back to the email step to pick someone else."""
        company = uow.companies.get(company_id)
        if company.status is CompanyStatus.EMAIL_READY:
            uow.companies.transition(
                company.id,
                CompanyStatus.CONTACTS_FOUND,
                expected_version=company.row_version,
                actor=actor,
                reason="a person was found not to work here",
                next_action_at=None,
            )

    def check_people(self, company_id: str, *, actor: str | None = None) -> PeopleCheck:
        """Look again at who a search found for this lead and set aside those who work elsewhere.

        One search per person (their profile's current headline), the free rules, then one
        model call for the rest. Nobody you confirmed, added, or wrote to is touched. Someone
        confirmed by mistake before is set aside; someone unsure stays for you to check.
        """
        actor = actor or self._actor
        if self._search is None:
            raise LeadError("searching is not set up (no Tavily key), so people cannot be checked")
        with self._uow(self._workspace_id) as uow:
            company = uow.companies.get(company_id)
            people = [
                c
                for c in uow.contacts.for_company(company_id)
                if c.source is ContactSource.SEARCH
                and c.status in (ContactStatus.UNCONFIRMED, ContactStatus.CANDIDATE)
                and c.linkedin_url
                and not uow.messages.for_contact(c.id)
                and not _confirmed_by_operator(uow, c.id)
            ]
        name = company.name or company.domain
        seen: list[tuple[Contact, Placement, str, str]] = []
        headlines = self._profile_headlines(people, company)
        for person in people:
            headline, employer, snippet = headlines.get(person.id, (person.title or "", "", ""))
            placed = place_by_rules(
                name=person.full_name or "",
                headline=headline,
                employer=employer,
                snippet=snippet,
                company=name,
                domain=company.domain,
            )
            seen.append((person, placed.placement, placed.reason, f"{headline} {snippet}"))
        open_ = [i for i, row in enumerate(seen) if row[1] is Placement.UNSURE]
        if open_ and self._llm is not None:
            summary = str((company.research or {}).get("summary") or "")
            with call_scope(company_id=company.id):
                verdicts = judge_people(
                    self._llm,
                    name,
                    company.domain,
                    summary,
                    [Candidate(seen[i][0].full_name or "", seen[i][3]) for i in open_],
                )
            for i, (placement, reason) in zip(open_, verdicts, strict=True):
                seen[i] = (seen[i][0], placement, reason, seen[i][3])
        counts = {Placement.WORKS_HERE: 0, Placement.NOT_HERE: 0, Placement.UNSURE: 0}
        with self._uow(self._workspace_id) as uow:
            for person, placement, reason, _ in seen:
                now = uow.contacts.get(person.id)
                counts[placement] += 1
                if placement is Placement.NOT_HERE and CONTACT.allows(
                    now.status, ContactStatus.NOT_HERE
                ):
                    uow.contacts.transition(
                        person.id,
                        ContactStatus.NOT_HERE,
                        actor=actor,
                        reason="checked: does not work here",
                        placement_note=reason,
                    )
                elif now.status is ContactStatus.UNCONFIRMED and now.placement_note != reason:
                    uow.contacts.set_placement_note(person.id, reason)
            if counts[Placement.NOT_HERE]:
                self._drop_recipient(uow, company_id, actor)
            uow.commit()
        return PeopleCheck(
            checked=len(seen),
            works_here=counts[Placement.WORKS_HERE],
            not_here=counts[Placement.NOT_HERE],
            unsure=counts[Placement.UNSURE],
        )

    def _profile_headlines(
        self, people: list[Contact], company: Company
    ) -> dict[str, tuple[str, str, str]]:
        """(job title, employer, snippet) from each person's public profile result, a few people
        per search; a person whose profile was not in the results is left out."""
        search = self._search
        if search is None or not people:
            return {}
        slugs = {
            (p.linkedin_url or "").rstrip("/").rsplit("/", 1)[-1].lower(): p.id for p in people
        }
        found: dict[str, tuple[str, str, str]] = {}
        for start in range(0, len(people), NAMES_PER_SEARCH):
            chunk = people[start : start + NAMES_PER_SEARCH]
            names = " OR ".join(f'"{p.full_name}"' for p in chunk if p.full_name)
            with call_scope(company_id=company.id):
                try:
                    hits = search.search(
                        f"site:linkedin.com/in ({names})", max_results=4 * len(chunk) + 1
                    )
                except ProviderError:
                    continue
            for hit in hits:
                slug = hit.url.split("?")[0].rstrip("/").rsplit("/", 1)[-1].lower()
                contact_id = slugs.get(slug)
                if contact_id and contact_id not in found and "/in/" in hit.url.lower():
                    _, title, employer = read_profile_title(hit.title)
                    found[contact_id] = (title, employer, hit.snippet)
        return found

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
            open_emails = [
                m
                for m in uow.messages.for_company(company_id)
                if m.state in (MessageState.GENERATED, MessageState.APPROVED)
            ]
            if open_emails:  # throwing an email away to have it written again costs a rewrite
                left, renews = credit_left(uow, utcnow())
                if not left:
                    raise LeadError(
                        f"no AI credits are left; they renew on {renews:%d %b}. "
                        "Ask your admin for more in Settings → Plan and usage."
                    )
                uow.usage.charge(UsageStep.REWRITE, company_id)
            for message in open_emails:
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


def _confirmed_by_operator(uow: UnitOfWork, contact_id: str) -> bool:
    return any(
        e.type == "status_changed" and e.data.get("reason") == CONFIRMED_WORKS_HERE
        for e in uow.events.for_entities([(EntityType.CONTACT, contact_id)])
    )


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


# Who is looked for at a lead with no campaign (and so no job titles of its own).
_FOUNDER_TITLES = ("Founder", "CEO", "CTO")


def _clean_profile(uow: UnitOfWork, contact_id: str, url: str) -> str | None:
    """A LinkedIn profile address made plain, or None for "" (remove it). Refused when it is
    not a profile link, or another person in this workspace already has it."""
    if not url.strip():
        return None
    plain = profile_address(url.strip() if "://" in url else f"https://{url.strip()}")
    if plain is None:
        raise InvalidInput("give a LinkedIn profile link, such as https://www.linkedin.com/in/name")
    if plain != uow.contacts.get(contact_id).linkedin_url and uow.contacts.linkedin_taken(plain):
        raise InvalidInput("another person in this workspace already has that LinkedIn profile")
    return plain


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
        row.credits_milli,
        row.latency_ms,
        row.contact_id,
        (row.detail or {}).get("asked", ""),
        (row.detail or {}).get("got", ""),
    )
