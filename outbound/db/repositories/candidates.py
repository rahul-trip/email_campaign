"""Companies discovery found, and what it decided about each (``discovery_candidates``)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select

from outbound.db.models import CompanyRow, DiscoveryCandidateRow
from outbound.db.repositories.base import ScopedRepository, snapshot
from outbound.domain.discovery import QUALIFIED, SourceYield, name_key
from outbound.domain.entities import DiscoveryCandidate
from outbound.domain.enums import CandidateVerdict


class CandidateRepository(ScopedRepository):
    def add(
        self,
        *,
        campaign_id: str,
        run_id: str | None,
        name: str,
        name_key: str,
        verdict: CandidateVerdict,
        domain: str | None = None,
        sources: Sequence[str] = (),
        source_urls: Sequence[str] = (),
        description: str = "",
        evidence: str = "",
        screen_score: int | None = None,
        rank_score: int | None = None,
        reason: str = "",
        company_id: str | None = None,
    ) -> DiscoveryCandidate:
        row = DiscoveryCandidateRow(
            workspace_id=self._workspace_id,
            campaign_id=campaign_id,
            run_id=run_id,
            name=name[:300],
            name_key=name_key[:300],
            domain=domain,
            sources=list(sources),
            source_urls=list(source_urls),
            description=description,
            evidence=evidence,
            screen_score=screen_score,
            rank_score=rank_score,
            verdict=verdict,
            reason=reason,
            company_id=company_id,
        )
        self._session.add(row)
        self._session.flush()
        return snapshot(row, DiscoveryCandidate)

    def get(self, candidate_id: str) -> DiscoveryCandidate:
        return snapshot(self._row(DiscoveryCandidateRow, candidate_id), DiscoveryCandidate)

    def for_run(self, run_id: str) -> list[DiscoveryCandidate]:
        """A run's candidates, best ranked first."""
        stmt = (
            select(DiscoveryCandidateRow)
            .where(
                DiscoveryCandidateRow.workspace_id == self._workspace_id,
                DiscoveryCandidateRow.run_id == run_id,
            )
            .order_by(
                DiscoveryCandidateRow.rank_score.desc().nulls_last(),
                DiscoveryCandidateRow.created_at,
            )
        )
        return [snapshot(row, DiscoveryCandidate) for row in self._session.scalars(stmt)]

    def waiting(self, campaign_id: str, limit: int) -> list[DiscoveryCandidate]:
        """Companies that fit but were not added: over an earlier run's limit, or with no website
        found then. Over-limit ones first, each best first: the next run adds these before it
        looks for more, and looks again for the missing websites."""
        stmt = (
            select(DiscoveryCandidateRow)
            .where(
                DiscoveryCandidateRow.workspace_id == self._workspace_id,
                DiscoveryCandidateRow.campaign_id == campaign_id,
                DiscoveryCandidateRow.verdict.in_(
                    [CandidateVerdict.OVER_LIMIT, CandidateVerdict.UNRESOLVED]
                ),
            )
            .order_by(
                (DiscoveryCandidateRow.verdict != CandidateVerdict.OVER_LIMIT),
                DiscoveryCandidateRow.rank_score.desc().nulls_last(),
                DiscoveryCandidateRow.created_at,
            )
            .limit(limit)
        )
        return [snapshot(row, DiscoveryCandidate) for row in self._session.scalars(stmt)]

    def known_keys(self, campaign_id: str) -> set[str]:
        """The companies already screened for this campaign: each one's key (its website, or
        its name key without one) and its name key, so a later mention of it without a
        website is recognised too."""
        stmt = select(DiscoveryCandidateRow.name_key, DiscoveryCandidateRow.name).where(
            DiscoveryCandidateRow.workspace_id == self._workspace_id,
            DiscoveryCandidateRow.campaign_id == campaign_id,
        )
        keys: set[str] = set()
        for key, name in self._session.execute(stmt):
            keys |= {key, name_key(name)} - {""}
        return keys

    def read_urls(self, campaign_id: str) -> set[str]:
        """Every page a candidate of this campaign was found on, so it is not read again."""
        stmt = select(DiscoveryCandidateRow.source_urls).where(
            DiscoveryCandidateRow.workspace_id == self._workspace_id,
            DiscoveryCandidateRow.campaign_id == campaign_id,
        )
        return {url for urls in self._session.scalars(stmt) for url in urls or []}

    def source_yield(self, *, since: datetime) -> dict[str, SourceYield]:
        """For each source, the companies it named since ``since``, how many became leads and
        how many of those passed the fit gate. A company two sources named counts for both."""
        stmt = (
            select(DiscoveryCandidateRow.sources, DiscoveryCandidateRow.company_id,
                   CompanyRow.status)
            .outerjoin(
                CompanyRow,
                (CompanyRow.id == DiscoveryCandidateRow.company_id)
                & (CompanyRow.workspace_id == self._workspace_id),
            )
            .where(
                DiscoveryCandidateRow.workspace_id == self._workspace_id,
                DiscoveryCandidateRow.created_at >= since,
            )
        )  # fmt: skip
        found: Counter[str] = Counter()
        leads: Counter[str] = Counter()
        qualified: Counter[str] = Counter()
        for sources, company_id, status in self._session.execute(stmt):
            for source in sources or []:
                found[source] += 1
                leads[source] += company_id is not None
                qualified[source] += status in QUALIFIED
        return {
            s: SourceYield(found=n, qualified=qualified[s], leads=leads[s])
            for s, n in found.items()
        }

    def decide(
        self,
        candidate_id: str,
        verdict: CandidateVerdict,
        *,
        reason: str,
        company_id: str | None = None,
        domain: str | None = None,
        run_id: str | None = None,
    ) -> DiscoveryCandidate:
        """A new verdict for a company found earlier (a later run added it, or a person did).
        The run that decided it is recorded, so it shows on that run's page."""
        row = self._row(DiscoveryCandidateRow, candidate_id)
        row.verdict = verdict
        row.reason = reason
        if company_id is not None:
            row.company_id = company_id
        if domain is not None:
            row.domain = domain
        if run_id is not None:
            row.run_id = run_id
        self._session.flush()
        return snapshot(row, DiscoveryCandidate)
