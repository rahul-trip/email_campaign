"""Stage 2: research one company and move it from ``new`` to ``researched``."""

from __future__ import annotations

from typing import Any

from outbound.db.uow import UnitOfWork
from outbound.domain.enums import CompanyStatus, ContactSource, LegalEntityType
from outbound.stages.base import StageContext, StageResult
from outbound.stages.research.graph import (
    Person,
    ResearchDeps,
    ResearchInput,
    build_research_graph,
    run_research,
)


class ResearchStage:
    name = "research"
    input_status = CompanyStatus.NEW
    guard_policy = False
    spends = True

    def __init__(self, deps: ResearchDeps) -> None:
        self._graph = build_research_graph(deps)

    def handle(self, ctx: StageContext) -> StageResult:
        company = ctx.company
        known = ctx.read(
            lambda uow: (uow.contacts.for_company(company.id), uow.notes.for_company(company.id))
        )
        contacts, notes = known
        campaign = ctx.campaign
        icp = (campaign.icp_description if campaign else None) or str(
            ctx.workspace.sender_profile.get("narrative") or ""
        )
        output = run_research(
            self._graph,
            ResearchInput(
                domain=company.domain,
                company_name=company.name or company.domain.split(".")[0].title(),
                country_code=company.country_code,
                notes="\n".join(n.body for n in notes),
                icp=icp,
                questions=campaign.research_questions if campaign else (),
                target_titles=campaign.target_titles if campaign else (),
                has_operator_contact=any(c.source is ContactSource.OPERATOR for c in contacts),
            ),
        )

        updates: dict[str, Any] = {
            "research": output.research,
            "research_answers": output.answers,
            "fit_score": output.fit_score,
            "fit_reason": output.fit_reason,
        }
        if output.country_code and not company.country_code:
            updates["country_code"] = output.country_code
        if output.legal_entity_type is not LegalEntityType.UNKNOWN:
            updates["legal_entity_type"] = output.legal_entity_type
        return StageResult(
            CompanyStatus.RESEARCHED,
            reason="researched",
            company_updates=updates,
            write=lambda uow: _save_people(uow, company.id, output.people),
        )


def _save_people(uow: UnitOfWork, company_id: str, people: tuple[Person, ...]) -> None:
    rank = len(uow.contacts.for_company(company_id))
    for person in people:
        if person.linkedin_url and uow.contacts.linkedin_taken(person.linkedin_url):
            continue
        rank += 1
        first, _, last = person.name.partition(" ")
        uow.contacts.add(
            company_id,
            rank=rank,
            source=ContactSource.SEARCH if person.source == "search" else ContactSource.SITE,
            full_name=person.name,
            first_name=first or None,
            last_name=last or None,
            title=person.title or None,
            linkedin_url=person.linkedin_url,
        )
