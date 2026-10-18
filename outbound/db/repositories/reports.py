"""Read-only questions about how the engine is doing: quality, holds and spend."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, func, select

from outbound.db.models import CompanyRow, MessageRow, ProviderCallRow
from outbound.db.repositories.base import ScopedRepository
from outbound.domain.enums import CallOutcome, CompanyStatus, HoldReason, MessageState


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


class ReportRepository(ScopedRepository):
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
