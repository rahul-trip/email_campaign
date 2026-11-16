"""The two reports that tell you whether to trust the engine and what it costs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from outbound.db.types import utcnow
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.discovery import YIELD_DAYS, SourceYield
from outbound.domain.enums import (
    CallOutcome,
    CandidateVerdict,
    CompanyStatus,
    HoldReason,
    MessageState,
)

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


@dataclass(frozen=True)
class StatusReport:
    by_status: dict[CompanyStatus, int]
    held: dict[HoldReason, int]
    waiting_for_review: int


@dataclass(frozen=True)
class VendorErrors:
    provider: str
    calls: int  # calls that reached the vendor (cache hits are not counted)
    errors: int

    @property
    def error_rate(self) -> float:
        return self.errors / self.calls if self.calls else 0.0


@dataclass(frozen=True)
class FunnelReport:
    """From a company found to a draft waiting in Review, over the last ``days``: what
    discovery named and what became of it, where the leads added are now, and which vendors
    are failing. The baseline each change to lead quality is measured against."""

    days: int
    named: int  # companies discovery named
    judged: int  # of those, scored by the model (the rest never were)
    verdicts: dict[CandidateVerdict, int]
    leads: int  # companies added in the period, by any route
    outcomes: dict[str, int]  # where they are now, see ``outcome``
    vendors: list[VendorErrors]

    @property
    def judged_share(self) -> float | None:
        return self.judged / self.named if self.named else None

    @property
    def lead_share(self) -> float | None:
        """Leads per company named: what screening lets through."""
        return self.verdicts.get(CandidateVerdict.ACCEPTED, 0) / self.named if self.named else None


def outcome(status: CompanyStatus, hold_reason: HoldReason | None, failed_stage: str | None) -> str:
    """Where a lead is, as one key: ``waiting``, ``failed:<stage>``, ``held:<reason>``, or its
    status (``disqualified``, ``email_ready``, ``copy_ready``...)."""
    if status is CompanyStatus.NEW:
        return "waiting"
    if status is CompanyStatus.FAILED:
        return f"failed:{failed_stage or 'unknown'}"
    if status is CompanyStatus.HELD:
        return f"held:{hold_reason.value if hold_reason else 'unknown'}"
    return status.value


class ReportService:
    def __init__(self, uow_factory: UnitOfWorkFactory, workspace_id: str) -> None:
        self._uow = uow_factory
        self._workspace_id = workspace_id

    def status(self) -> StatusReport:
        """Where every lead is, why some are held, and how many emails await review."""
        with self._uow(self._workspace_id) as uow:
            return StatusReport(
                by_status=uow.companies.count_by_status(),
                held=uow.reports.company_counts()[1],
                waiting_for_review=uow.messages.count_in_state(MessageState.GENERATED),
            )

    def quality(self) -> QualityReport:
        with self._uow(self._workspace_id) as uow:
            touch = uow.reports.touch_one()
            companies, holds = uow.reports.company_counts()
        return QualityReport(
            touch.written, touch.flagged, touch.sent, touch.unedited, companies, holds
        )

    def funnel(self, days: int = 30) -> FunnelReport:
        since = utcnow() - timedelta(days=days)
        with self._uow(self._workspace_id) as uow:
            candidates = uow.reports.candidate_counts(since)
            leads = uow.reports.lead_outcomes(since)
            errors = uow.reports.errors_by_provider(since, utcnow() + timedelta(seconds=1))
        outcomes: dict[str, int] = {}
        for lead in leads:
            key = outcome(lead.status, lead.hold_reason, lead.failed_stage)
            outcomes[key] = outcomes.get(key, 0) + lead.count
        return FunnelReport(
            days=days,
            named=sum(candidates.by_verdict.values()),
            judged=candidates.judged,
            verdicts=candidates.by_verdict,
            leads=sum(outcomes.values()),
            outcomes=dict(sorted(outcomes.items(), key=lambda item: -item[1])),
            vendors=[VendorErrors(e.provider, e.calls, e.errors) for e in errors],
        )

    def sources(self, days: int = YIELD_DAYS) -> list[tuple[str, SourceYield]]:
        """Where discovery's companies came from in the last ``days``, and how many of each
        source's leads passed the fit gate: the record discovery weighs its sources by. Best
        first."""
        with self._uow(self._workspace_id) as uow:
            found = uow.candidates.source_yield(since=utcnow() - timedelta(days=days))
        return sorted(found.items(), key=lambda item: (-item[1].rate, -item[1].found, item[0]))

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
