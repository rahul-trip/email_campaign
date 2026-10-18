"""The two reports that tell you whether to trust the engine and what it costs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import CallOutcome, HoldReason

CATCH_ALL_HOLDS = (HoldReason.CATCH_ALL_RESOLVING, HoldReason.CATCH_ALL_UNVERIFIED)
QUALITY_TARGET = 0.8  # the Phase 2 gate: 8 of the first 10 sent without edits


@dataclass(frozen=True)
class QualityReport:
    written: int
    flagged: int
    sent: int
    unedited: int
    companies: int
    holds: dict[HoldReason, int]

    @property
    def unedited_share(self) -> float | None:
        return self.unedited / self.sent if self.sent else None

    @property
    def flag_rate(self) -> float | None:
        return self.flagged / self.written if self.written else None

    def held_share(self, reason: HoldReason) -> float | None:
        return self.holds.get(reason, 0) / self.companies if self.companies else None

    @property
    def catch_all_share(self) -> float | None:
        held = sum(self.holds.get(reason, 0) for reason in CATCH_ALL_HOLDS)
        return held / self.companies if self.companies else None


@dataclass(frozen=True)
class CostReport:
    since: datetime
    until: datetime
    by_provider: dict[str, int] = field(default_factory=dict)
    calls_by_provider: dict[str, int] = field(default_factory=dict)
    prospects: int = 0
    outcomes: dict[CallOutcome, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.by_provider.values())

    @property
    def paid_calls(self) -> int:
        return self.outcomes.get(CallOutcome.HIT, 0) + self.outcomes.get(CallOutcome.MISS, 0)

    @property
    def per_prospect(self) -> int | None:
        return self.total // self.prospects if self.prospects else None


class ReportService:
    def __init__(self, uow_factory: UnitOfWorkFactory, workspace_id: str) -> None:
        self._uow = uow_factory
        self._workspace_id = workspace_id

    def quality(self) -> QualityReport:
        with self._uow(self._workspace_id) as uow:
            touch = uow.reports.touch_one()
            companies, holds = uow.reports.company_counts()
        return QualityReport(
            touch.written, touch.flagged, touch.sent, touch.unedited, companies, holds
        )

    def cost(self, since: datetime, until: datetime) -> CostReport:
        with self._uow(self._workspace_id) as uow:
            providers = uow.reports.spend_by_provider(since, until)
            prospects = [
                row for row in uow.reports.spend_by_company(since, until) if row.cost_micro_usd
            ]
            outcomes = uow.reports.call_outcomes(since, until)
        return CostReport(
            since,
            until,
            {row.key: row.cost_micro_usd for row in providers},
            {row.key: row.calls for row in providers},
            len(prospects),
            outcomes,
        )
