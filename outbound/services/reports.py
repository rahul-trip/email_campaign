"""The two reports that tell you whether to trust the engine and what it costs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from outbound.db.repositories.reports import DayRow, LeadSummary
from outbound.db.types import utcnow
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.brief import Brief
from outbound.domain.discovery import (
    CH,
    SOURCE_ORDER,
    STARTUP_SOURCES,
    YIELD_DAYS,
    SourceYield,
    plan_sources,
    share,
)
from outbound.domain.enums import (
    CallOutcome,
    CandidateVerdict,
    CompanyStatus,
    FailureKind,
    HoldReason,
    MessageState,
)
from outbound.domain.outcomes import Bucket

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
    by_provider: dict[str, int] = field(default_factory=dict)  # AI credits, in thousandths
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
    waiting_hot: int  # of those, the ones whose lead scores above 80
    buckets: dict[Bucket, int]


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


@dataclass(frozen=True)
class FitReport:
    """How the active campaign's companies spread over fit scores, in bands of ten."""

    campaign_id: str | None
    campaign: str | None
    min_fit_score: int | None
    bands: list[tuple[int, int]]  # (band start 0, 10, ... 90, count); 90 holds 90 to 100
    unscored: int

    @property
    def scored(self) -> int:
        return sum(n for _, n in self.bands)


@dataclass(frozen=True)
class PlannedSource:
    source: str
    suited: bool  # the brief allows it; whether its vendor key is set is known only at run time
    why_not: str | None
    share: float  # how much of the usual amount it would be asked for (0.5 to 2)
    record: SourceYield | None


@dataclass(frozen=True)
class DiscoveryPlan:
    campaign: str | None
    sources: list[PlannedSource]  # suited ones in the order discovery would ask them, then the rest


def review_streak(days: list[DayRow]) -> int:
    """Consecutive days with a review by a person, counting back from today; a day not yet
    reviewed today does not break a streak that ran to yesterday."""
    streak = 0
    for n, row in enumerate(reversed(days)):
        if row.reviewed:
            streak += 1
        elif n > 0:
            break
    return streak


def outcome(
    status: CompanyStatus,
    hold_reason: HoldReason | None,
    failed_stage: str | None,
    failure_kind: FailureKind | None = None,
) -> str:
    """Where a lead is, as one key: ``waiting``, ``failed:<stage>`` (a step broke),
    ``screened:no_person`` or ``screened:no_email`` (nobody to write to), ``held:<reason>``, or
    its status (``disqualified``, ``email_ready``, ``copy_ready``...)."""
    if status is CompanyStatus.NEW:
        return "waiting"
    if status is CompanyStatus.FAILED:
        if failure_kind in (FailureKind.NO_PERSON, FailureKind.NO_EMAIL):
            return f"screened:{failure_kind.value}"
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
                waiting_hot=uow.messages.count_waiting_hot(),
                buckets=uow.companies.count_buckets(),
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
            key = outcome(lead.status, lead.hold_reason, lead.failed_stage, lead.failure_kind)
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
                row for row in uow.reports.spend_by_company(since, until) if row.credits_milli
            ]
            outcomes = uow.reports.call_outcomes(since, until)
        return CostReport(
            since,
            until,
            {row.key: row.credits_milli for row in providers},
            {row.key: row.calls for row in providers},
            len(prospects),
            outcomes,
        )

    # ------------------------------------------------------------------ web3 read models

    def daily(self, days: int = 14) -> list[DayRow]:
        """Per-day counts for the last ``days`` days, today included, oldest first."""
        now = utcnow()
        since = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
        with self._uow(self._workspace_id) as uow:
            return uow.reports.daily(since, now + timedelta(seconds=1))

    def fit(self) -> FitReport:
        """Fit-score bands for the active campaign (every company when none is active)."""
        with self._uow(self._workspace_id) as uow:
            campaign = uow.campaigns.active()
            scores, unscored = uow.reports.fit_scores(campaign.id if campaign else None)
        bands = dict.fromkeys(range(0, 100, 10), 0)
        for score, n in scores.items():
            bands[min(max(score, 0), 99) // 10 * 10] += n
        return FitReport(
            campaign.id if campaign else None,
            campaign.name if campaign else None,
            campaign.min_fit_score if campaign else None,
            sorted(bands.items()),
            unscored,
        )

    def lead_summaries(self, company_ids: list[str]) -> dict[str, LeadSummary]:
        with self._uow(self._workspace_id) as uow:
            return uow.reports.lead_summaries(company_ids)

    def discovery_plan(self) -> DiscoveryPlan:
        """Which sources the next discovery run would ask for the active campaign, best record
        first, and why the others would be skipped. Read-only: nothing is searched."""
        with self._uow(self._workspace_id) as uow:
            campaign = uow.campaigns.active()
            yields = uow.candidates.source_yield(since=utcnow() - timedelta(days=YIELD_DAYS))
        brief = Brief.from_json(campaign.icp_brief) if campaign else Brief()
        order = plan_sources(brief, available=SOURCE_ORDER, yields=yields)
        planned = [
            PlannedSource(name, True, None, round(share(name, yields), 2), yields.get(name))
            for name in order
        ]
        for name in SOURCE_ORDER:
            if name not in order:
                why = (
                    "only for a brief that looks for start-ups"
                    if name in STARTUP_SOURCES
                    else "only for a UK brief with industry (SIC) codes"
                    if name == CH
                    else "not suited to this brief"
                )
                planned.append(PlannedSource(name, False, why, 0.0, yields.get(name)))
        return DiscoveryPlan(campaign.name if campaign else None, planned)
