"""Stage 4: rank the people research found against the job titles the campaign wants.

Ranking is plain title matching and a seniority order (see ``domain.ranking``). A person the
operator added, gave an address to, or recorded a consent for stays first. Only the top few are
worked on, so the email stage never spends money on the fifth name on a team page.
"""

from __future__ import annotations

from outbound.db.uow import UnitOfWork
from outbound.domain.actors import SYSTEM
from outbound.domain.entities import Contact
from outbound.domain.enums import WORKABLE_CONTACT_STATUSES, CompanyStatus, Provenance
from outbound.domain.ranking import RankedContact, rank_contacts
from outbound.stages.base import StageContext, StageFailure, StageResult


class ContactsStage:
    name = "contacts"
    input_status = CompanyStatus.QUALIFIED
    guard_policy = True
    spends = False

    def handle(self, ctx: StageContext) -> StageResult:
        company_id = ctx.company.id
        usable = [
            c
            for c in ctx.read(lambda uow: uow.contacts.for_company(company_id))
            if c.status in WORKABLE_CONTACT_STATUSES
        ]
        if not usable:
            raise StageFailure("no decision-maker was found on the site or in a public search")
        wanted = ctx.campaign.target_titles if ctx.campaign else ()
        chosen = ctx.read(lambda uow: operator_chosen(uow, usable))
        ranked = rank_contacts(usable, wanted, chosen)
        return StageResult(
            CompanyStatus.CONTACTS_FOUND,
            reason=f"{len(ranked)} contact(s) ranked",
            write=lambda uow: _save_ranking(uow, ranked),
        )


def operator_chosen(uow: UnitOfWork, contacts: list[Contact]) -> set[str]:
    """People the operator picked without adding them: they gave an address or a consent."""
    return {
        c.id
        for c in contacts
        if uow.consents.has_active(c.id)
        or any(e.provenance is Provenance.OPERATOR_GIVEN for e in uow.emails.for_contact(c.id))
    }


def _save_ranking(uow: UnitOfWork, ranked: list[RankedContact]) -> None:
    for item in ranked:
        _apply(uow, item.contact, item)


def _apply(uow: UnitOfWork, contact: Contact, item: RankedContact) -> None:
    changes: dict[str, object] = {}
    if contact.rank != item.rank:
        changes["rank"] = item.rank
    if contact.seniority != item.seniority:
        changes["seniority"] = item.seniority
    if changes:
        uow.contacts.update_fields(contact.id, changes, actor=SYSTEM)
