"""Stage 4: rank the people research found against the job titles the campaign wants.

Ranking is plain title matching and a seniority order (see ``domain.ranking``). An operator-given
person stays first. Only the top few are worked on, so the email stage never spends money on
the fifth name on a team page.
"""

from __future__ import annotations

from outbound.db.uow import UnitOfWork
from outbound.domain.actors import SYSTEM
from outbound.domain.entities import Contact
from outbound.domain.enums import CompanyStatus, ContactStatus
from outbound.domain.ranking import RankedContact, rank_contacts
from outbound.stages.base import StageContext, StageFailure, StageResult

MAX_ACTIVE_CONTACTS = 3
_USABLE = (ContactStatus.CANDIDATE, ContactStatus.ACTIVE)


class ContactsStage:
    name = "contacts"
    input_status = CompanyStatus.QUALIFIED
    guard_policy = True

    def handle(self, ctx: StageContext) -> StageResult:
        company_id = ctx.company.id
        usable = [
            c
            for c in ctx.read(lambda uow: uow.contacts.for_company(company_id))
            if c.status in _USABLE
        ]
        if not usable:
            raise StageFailure("no decision-maker was found on the site or in a public search")
        wanted = ctx.campaign.target_titles if ctx.campaign else ()
        ranked = rank_contacts(usable, wanted)
        return StageResult(
            CompanyStatus.CONTACTS_FOUND,
            reason=f"{min(len(ranked), MAX_ACTIVE_CONTACTS)} contact(s) ranked",
            write=lambda uow: _save_ranking(uow, ranked),
        )


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
