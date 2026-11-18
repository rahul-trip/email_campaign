"""Stage 4: rank the people research found against the job titles the campaign wants.

Ranking is plain title matching and a seniority order (see ``domain.ranking``). A person the
operator added, gave an address to, or recorded a consent for stays first. Only the top few are
worked on, so the email stage never spends money on the fifth name on a team page.
"""

from __future__ import annotations

from outbound.db.uow import UnitOfWork
from outbound.domain.actors import SYSTEM
from outbound.domain.entities import Contact
from outbound.domain.enums import (
    WORKABLE_CONTACT_STATUSES,
    CompanyStatus,
    ContactStatus,
    FailureKind,
    Provenance,
)
from outbound.domain.ranking import RankedContact, can_be_written_to, rank_contacts
from outbound.domain.sender import sender_for
from outbound.logging import get_logger
from outbound.providers.errors import BudgetExceeded, ProviderError
from outbound.providers.ports import LlmClient
from outbound.stages.base import StageContext, StageFailure, StageResult
from outbound.stages.linkedin import LinkedInDraft, LinkedInLead, write_linkedin_many

log = get_logger(__name__)
LINKEDIN_PEOPLE = 3  # the people worth a hand-written LinkedIn message, as many as the email tries


class ContactsStage:
    name = "contacts"
    input_status = CompanyStatus.QUALIFIED
    guard_policy = True

    def __init__(self, llm: LlmClient | None = None) -> None:
        # With a model, the step also writes LinkedIn drafts for the people it ranks, so it spends.
        self._llm = llm
        self.spends = llm is not None

    def handle(self, ctx: StageContext) -> StageResult:
        company_id = ctx.company.id
        usable = [
            c
            for c in ctx.read(lambda uow: uow.contacts.for_company(company_id))
            if c.status in WORKABLE_CONTACT_STATUSES
        ]
        if not usable:
            everyone = ctx.read(lambda uow: uow.contacts.for_company(company_id))
            if everyone and all(c.status is ContactStatus.NOT_HERE for c in everyone):
                raise StageFailure(
                    "everyone a search found works at another company: add a person you know"
                    " on the lead page",
                    FailureKind.NO_PERSON,
                )
            if any(c.status is ContactStatus.UNCONFIRMED for c in everyone):
                raise StageFailure(
                    "the only people found could not be confirmed to work here: confirm one on"
                    " the lead page, or add a person you know"
                )
            raise StageFailure(
                "no decision-maker was found on the site or in a public search",
                FailureKind.NO_PERSON,
            )
        wanted = ctx.campaign.target_titles if ctx.campaign else ()
        chosen = ctx.read(lambda uow: operator_chosen(uow, usable))
        if not any(can_be_written_to(c, wanted, chosen) for c in usable):
            raise StageFailure(
                "people were found, but none is a decision-maker (a founder, C-level, vice"
                " president, director or one of the campaign's job titles): add the person you"
                " want to write to on the lead page, then retry",
                FailureKind.NO_PERSON,
            )
        ranked = rank_contacts(usable, wanted, chosen)
        written = self._drafts(ctx, [r.contact for r in ranked], wanted, chosen)
        return StageResult(
            CompanyStatus.CONTACTS_FOUND,
            reason=f"{len(ranked)} contact(s) ranked",
            write=lambda uow: _save_ranking(uow, ranked, ctx.company.id, written),
        )

    def _drafts(
        self, ctx: StageContext, people: list[Contact], wanted: tuple[str, ...], chosen: set[str]
    ) -> list[tuple[Contact, LinkedInDraft]]:
        """A LinkedIn connection note and follow-up for each confirmed decision-maker who has a
        profile and no draft yet. Never fails the lead: a model error only means no draft."""
        if self._llm is None:
            return []
        profile = dict(ctx.workspace.sender_profile)
        if not profile.get("reviewed_at"):
            return []  # the copy step explains what is missing

        def load(uow: UnitOfWork):  # type: ignore[no-untyped-def]
            todo = [
                c
                for c in people
                if c.linkedin_url
                and can_be_written_to(c, wanted, chosen, first_counts=True)
                and uow.linkedin.for_contact(c.id) is None
            ][:LINKEDIN_PEOPLE]
            campaign = (
                uow.campaigns.get(ctx.company.campaign_id) if ctx.company.campaign_id else None
            )
            mailbox = (
                uow.mailboxes.get(campaign.mailbox_id) if campaign and campaign.mailbox_id else None
            )
            mailbox = mailbox or uow.mailboxes.default()
            notes = "\n".join(n.body for n in uow.notes.for_company(ctx.company.id))
            return todo, mailbox, notes

        todo, mailbox, notes = ctx.read(load)
        sender = sender_for(profile, mailbox.sender if mailbox else None)
        if not todo or not str(sender.get("signature_name") or "").strip():
            return []
        company = ctx.company
        named = [(c, c.first_name or next(iter((c.full_name or "").split()), "")) for c in todo]
        named = [(c, first) for c, first in named if first]
        if not named:
            return []
        try:  # one call for everyone at the lead, one more only for drafts that need fixing
            drafts = write_linkedin_many(
                self._llm,
                LinkedInLead(
                    sender=sender,
                    company_name=company.name or company.domain,
                    research=company.research or {},
                    notes=notes,
                ),
                [(first, c.title or "") for c, first in named],
            )
        except BudgetExceeded:
            raise
        except ProviderError as error:
            log.warning("linkedin_draft_failed", company_id=company.id, reason=str(error)[:200])
            return []
        return [(c, d) for (c, _), d in zip(named, drafts, strict=True) if d is not None]


def operator_chosen(uow: UnitOfWork, contacts: list[Contact]) -> set[str]:
    """People the operator picked without adding them: they gave an address or a consent."""
    return {
        c.id
        for c in contacts
        if uow.consents.has_active(c.id)
        or any(e.provenance is Provenance.OPERATOR_GIVEN for e in uow.emails.for_contact(c.id))
    }


def _save_ranking(
    uow: UnitOfWork,
    ranked: list[RankedContact],
    company_id: str,
    drafts: list[tuple[Contact, LinkedInDraft]],
) -> None:
    for item in ranked:
        _apply(uow, item.contact, item)
    for contact, draft in drafts:
        if uow.linkedin.for_contact(contact.id) is None:  # a rerun may have written it already
            uow.linkedin.create(
                company_id=company_id,
                contact_id=contact.id,
                note=draft.note,
                message=draft.message,
                issues=list(draft.issues),
            )


def _apply(uow: UnitOfWork, contact: Contact, item: RankedContact) -> None:
    changes: dict[str, object] = {}
    if contact.rank != item.rank:
        changes["rank"] = item.rank
    if contact.seniority != item.seniority:
        changes["seniority"] = item.seniority
    if changes:
        uow.contacts.update_fields(contact.id, changes, actor=SYSTEM)
