"""The companies a discovery run found, and making one a lead by hand.

Screening can be wrong, and a company with no confirmed website cannot be added on its own, so
the run's page lists every company found with its verdict and lets a person promote one. A
promoted company is the operator's choice: it is added as a manual lead (it skips the fit gate
and uses a manual credit, like a company typed in), through intake, so suppression and limits
apply as they would to any target.
"""

from __future__ import annotations

from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.actors import OPERATOR
from outbound.domain.domains import registrable_domain
from outbound.domain.entities import DiscoveryCandidate
from outbound.domain.enums import CandidateVerdict, CompanySource, ImportRowStatus, ImportSource
from outbound.domain.errors import InvalidInput
from outbound.services.intake import IntakeService


class CandidateService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        workspace_id: str,
        intake: IntakeService,
        *,
        actor: str = OPERATOR,
    ) -> None:
        self._uow = uow_factory
        self._workspace_id = workspace_id
        self._intake = intake
        self._actor = actor

    def for_run(self, run_id: str) -> list[DiscoveryCandidate]:
        with self._uow(self._workspace_id) as uow:
            uow.runs.get(run_id)  # NotFound for an unknown run or another workspace's
            return uow.candidates.for_run(run_id)

    def promote(self, candidate_id: str, domain: str | None = None) -> DiscoveryCandidate:
        with self._uow(self._workspace_id) as uow:
            candidate = uow.candidates.get(candidate_id)
        if candidate.verdict is CandidateVerdict.ACCEPTED:
            raise InvalidInput(f"{candidate.name} is a lead already.")
        website = registrable_domain(domain) if domain else candidate.domain
        if not website:
            raise InvalidInput(f"Give {candidate.name}'s website to add it as a lead.")
        report = self._intake.run(
            [{"website": website, "company": candidate.name, "notes": _note(candidate)}],
            source=ImportSource.UI,
            company_source=CompanySource.MANUAL,
            campaign_id=candidate.campaign_id,
            actor=self._actor,
        )
        [row] = report.rows
        if row.status is not ImportRowStatus.ACCEPTED:
            raise InvalidInput(f"{candidate.name} was not added: {row.reason or row.status.value}.")
        with self._uow(self._workspace_id) as uow:
            company = uow.companies.by_domain(website)
            promoted = uow.candidates.decide(
                candidate_id,
                CandidateVerdict.ACCEPTED,
                reason="added by hand",
                company_id=company.id if company else None,
                domain=website,
            )
            uow.commit()
        return promoted


def _note(candidate: DiscoveryCandidate) -> str:
    sources = ", ".join(candidate.sources) or "discovery"
    found = " | ".join(p for p in (candidate.evidence, *candidate.source_urls[:2]) if p)
    return f"Found by discovery ({sources}), added by hand: {found}"[:1_000]
