"""Read-only questions about how the engine is doing: quality, holds and spend."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, case, func, select

from outbound.db.models import CompanyRow, DiscoveryCandidateRow, MessageRow, ProviderCallRow
from outbound.db.repositories.base import ScopedRepository
from outbound.domain.enums import (
    CallOutcome,
    CandidateVerdict,
    CompanyStatus,
    HoldReason,
    MessageState,
)


@dataclass(frozen=True)
class TouchOneStats:
    written: int  # first emails generated, whatever became of them
    flagged: int  # of those, how many the linter flagged
    sent: int
    unedited: int  # of those sent, how many went out exactly as written


@dataclass(frozen=True)
class SpendRow:
    key: str
    cost_micro_usd: int
    calls: int


@dataclass(frozen=True)
class CandidateCounts:
    """Companies discovery named since a date, and what became of them."""

    by_verdict: dict[CandidateVerdict, int]
    judged: int  # of all, how many the model scored (the rest were never judged by it)


@dataclass(frozen=True)
class LeadOutcome:
    status: CompanyStatus
    hold_reason: HoldReason | None
    failed_stage: str | None
    count: int


@dataclass(frozen=True)
class ErrorRow:
    provider: str
    calls: int
    errors: int


class ReportRepository(ScopedRepository):
    def candidate_counts(self, since: datetime) -> CandidateCounts:
        where = (
            DiscoveryCandidateRow.workspace_id == self._workspace_id,
            DiscoveryCandidateRow.created_at >= since,
        )
        stmt = select(DiscoveryCandidateRow.verdict, func.count()).where(*where)
        by_verdict = {
            v: int(n)
            for v, n in self._session.execute(stmt.group_by(DiscoveryCandidateRow.verdict))
        }
        judged = self._session.scalar(
            select(func.count()).where(*where, DiscoveryCandidateRow.screen_score.is_not(None))
        )
        return CandidateCounts(by_verdict, int(judged or 0))

    def lead_outcomes(self, since: datetime) -> list[LeadOutcome]:
        """Where the companies added since a date are now: status, hold reason, failed stage."""
        stmt = (
            select(CompanyRow.status, CompanyRow.hold_reason, CompanyRow.failed_stage, func.count())
            .where(CompanyRow.workspace_id == self._workspace_id, CompanyRow.created_at >= since)
            .group_by(CompanyRow.status, CompanyRow.hold_reason, CompanyRow.failed_stage)
        )
        return [LeadOutcome(s, h, f, int(n)) for s, h, f, n in self._session.execute(stmt)]

    def errors_by_provider(self, since: datetime, until: datetime) -> list[ErrorRow]:
        """Calls that reached a vendor (not cache hits) and how many of them failed."""
        stmt = (
            select(
                ProviderCallRow.provider,
                func.count(),
                func.sum(case((ProviderCallRow.outcome == CallOutcome.ERROR, 1), else_=0)),
            )
            .where(
                *self._window(since, until),
                ProviderCallRow.outcome.in_([CallOutcome.HIT, CallOutcome.MISS, CallOutcome.ERROR]),
            )
            .group_by(ProviderCallRow.provider)
            .order_by(ProviderCallRow.provider)
        )
        return [ErrorRow(p, int(n), int(e or 0)) for p, n, e in self._session.execute(stmt)]

    def touch_one(self) -> TouchOneStats:
        stmt = select(MessageRow.state, MessageRow.edit_distance, MessageRow.lint_report).where(
            MessageRow.workspace_id == self._workspace_id,
            MessageRow.step == 0,
            MessageRow.state != MessageState.CANCELLED,
        )
        written = flagged = sent = unedited = 0
        for state, distance, lint_report in self._session.execute(stmt):
            written += 1
            flagged += bool((lint_report or {}).get("flagged"))
            if state in (MessageState.SENT, MessageState.BOUNCED):
                sent += 1
                unedited += distance == 0
        return TouchOneStats(written, flagged, sent, unedited)

    def company_counts(self) -> tuple[int, dict[HoldReason, int]]:
        """Total companies, and how many are held for each reason."""
        total = self._session.scalar(
            select(func.count())
            .select_from(CompanyRow)
            .where(CompanyRow.workspace_id == self._workspace_id)
        )
        stmt = (
            select(CompanyRow.hold_reason, func.count())
            .where(
                CompanyRow.workspace_id == self._workspace_id,
                CompanyRow.status == CompanyStatus.HELD,
            )
            .group_by(CompanyRow.hold_reason)
        )
        holds = {reason: count for reason, count in self._session.execute(stmt) if reason}
        return int(total or 0), holds

    def spend_by_provider(self, since: datetime, until: datetime) -> list[SpendRow]:
        stmt = (
            select(
                ProviderCallRow.provider,
                func.coalesce(func.sum(ProviderCallRow.cost_micro_usd), 0),
                func.count(),
            )
            .where(*self._window(since, until))
            .group_by(ProviderCallRow.provider)
            .order_by(ProviderCallRow.provider)
        )
        return [SpendRow(p, int(cost), int(n)) for p, cost, n in self._session.execute(stmt)]

    def spend_by_company(self, since: datetime, until: datetime) -> list[SpendRow]:
        stmt = (
            select(
                ProviderCallRow.company_id,
                func.coalesce(func.sum(ProviderCallRow.cost_micro_usd), 0),
                func.count(),
            )
            .where(*self._window(since, until), ProviderCallRow.company_id.is_not(None))
            .group_by(ProviderCallRow.company_id)
        )
        return [SpendRow(str(c), int(cost), int(n)) for c, cost, n in self._session.execute(stmt)]

    def call_outcomes(self, since: datetime, until: datetime) -> dict[CallOutcome, int]:
        stmt = (
            select(ProviderCallRow.outcome, func.count())
            .where(*self._window(since, until))
            .group_by(ProviderCallRow.outcome)
        )
        return {outcome: int(n) for outcome, n in self._session.execute(stmt)}

    def _window(self, since: datetime, until: datetime) -> tuple[ColumnElement[bool], ...]:
        return (
            ProviderCallRow.workspace_id == self._workspace_id,
            ProviderCallRow.created_at >= since,
            ProviderCallRow.created_at < until,
        )
