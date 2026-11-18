"""Read-only questions about how the engine is doing: quality, holds and spend."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import ColumnElement, case, func, select

from outbound.db.models import (
    CompanyRow,
    ContactEmailRow,
    ContactRow,
    DiscoveryCandidateRow,
    EventRow,
    MessageRow,
    ProviderCallRow,
)
from outbound.db.repositories.base import ScopedRepository
from outbound.domain.actors import AUTO, SYSTEM
from outbound.domain.enums import (
    CallOutcome,
    CandidateVerdict,
    CompanyStatus,
    ContactStatus,
    EntityType,
    FailureKind,
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
    credits_milli: int  # AI credits, in thousandths
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
    failure_kind: FailureKind | None
    count: int


@dataclass(frozen=True)
class ErrorRow:
    provider: str
    calls: int
    errors: int


@dataclass
class DayRow:
    """What happened on one UTC day."""

    day: date
    leads: int = 0  # companies added, by any route
    approved: int = 0  # emails approved, by a person or automatically
    reviewed: int = 0  # emails a person approved or rejected
    sent: int = 0  # emails seen in a Sent folder
    credits_milli: int = 0  # AI credits used, in thousandths


@dataclass(frozen=True)
class LeadSummary:
    """The one line a leads list shows about a company's people and spend."""

    company_id: str
    contact_name: str | None
    contact_title: str | None
    email_status: str | None
    credits_milli: int


# People the engine works on; the others (unconfirmed, not here, gone) are not "the contact".
_WORKED_ON = (ContactStatus.ACTIVE, ContactStatus.CANDIDATE)
_DECIDED = (MessageState.APPROVED.value, MessageState.REJECTED.value)


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
        """Where the companies added since a date are now: status, hold, failed stage and kind."""
        stmt = (
            select(
                CompanyRow.status,
                CompanyRow.hold_reason,
                CompanyRow.failed_stage,
                CompanyRow.failure_kind,
                func.count(),
            )
            .where(CompanyRow.workspace_id == self._workspace_id, CompanyRow.created_at >= since)
            .group_by(
                CompanyRow.status,
                CompanyRow.hold_reason,
                CompanyRow.failed_stage,
                CompanyRow.failure_kind,
            )
        )
        return [LeadOutcome(s, h, f, k, int(n)) for s, h, f, k, n in self._session.execute(stmt)]

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
        # An email the engine approved by itself was never chosen by a person, so it says
        # nothing about whether people accept what is written: left out of "sent unedited".
        automatic = set(
            self._session.scalars(
                select(EventRow.entity_id).where(
                    EventRow.workspace_id == self._workspace_id,
                    EventRow.entity_type == EntityType.MESSAGE,
                    EventRow.actor == AUTO,
                )
            )
        )
        stmt = select(
            MessageRow.id, MessageRow.state, MessageRow.edit_distance, MessageRow.lint_report
        ).where(
            MessageRow.workspace_id == self._workspace_id,
            MessageRow.step == 0,
            MessageRow.state != MessageState.CANCELLED,
        )
        written = flagged = sent = unedited = 0
        for message_id, state, distance, lint_report in self._session.execute(stmt):
            written += 1
            flagged += bool((lint_report or {}).get("flagged"))
            if message_id in automatic:
                continue
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
                func.coalesce(func.sum(ProviderCallRow.credits_milli), 0),
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
                func.coalesce(func.sum(ProviderCallRow.credits_milli), 0),
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

    # ------------------------------------------------------------------ web3 read models

    def daily(self, since: datetime, until: datetime) -> list[DayRow]:
        """One row per UTC day from ``since`` to ``until``, oldest first, days with nothing
        included. Grouped here rather than in SQL so SQLite and Postgres agree."""
        days: dict[date, DayRow] = {}
        cursor = since.date()
        while cursor <= until.date():
            days[cursor] = DayRow(cursor)
            cursor = date.fromordinal(cursor.toordinal() + 1)

        def bump(moment: datetime | None, field: str, by: int = 1) -> None:
            if moment is not None and moment.date() in days:
                row = days[moment.date()]
                setattr(row, field, getattr(row, field) + by)

        for (created,) in self._session.execute(
            select(CompanyRow.created_at).where(
                CompanyRow.workspace_id == self._workspace_id,
                CompanyRow.created_at >= since,
                CompanyRow.created_at < until,
            )
        ):
            bump(created, "leads")
        for created, actor, data in self._session.execute(
            select(EventRow.created_at, EventRow.actor, EventRow.data).where(
                EventRow.workspace_id == self._workspace_id,
                EventRow.entity_type == EntityType.MESSAGE,
                EventRow.type == "status_changed",
                EventRow.created_at >= since,
                EventRow.created_at < until,
            )
        ):
            to = (data or {}).get("to")
            if to == MessageState.APPROVED.value:
                bump(created, "approved")
            if to in _DECIDED and actor not in (SYSTEM, AUTO):
                bump(created, "reviewed")
        for (sent_at,) in self._session.execute(
            select(MessageRow.sent_at).where(
                MessageRow.workspace_id == self._workspace_id,
                MessageRow.sent_at >= since,
                MessageRow.sent_at < until,
            )
        ):
            bump(sent_at, "sent")
        for created, cost in self._session.execute(
            select(ProviderCallRow.created_at, ProviderCallRow.credits_milli).where(
                *self._window(since, until), ProviderCallRow.credits_milli > 0
            )
        ):
            bump(created, "credits_milli", int(cost))
        return list(days.values())

    def fit_scores(self, campaign_id: str | None) -> tuple[dict[int, int], int]:
        """How many companies have each fit score, and how many have none yet, for one campaign
        (or every company when ``campaign_id`` is None)."""
        where = [CompanyRow.workspace_id == self._workspace_id]
        if campaign_id is not None:
            where.append(CompanyRow.campaign_id == campaign_id)
        stmt = select(CompanyRow.fit_score, func.count()).where(*where)
        scores: dict[int, int] = {}
        unscored = 0
        for score, n in self._session.execute(stmt.group_by(CompanyRow.fit_score)):
            if score is None:
                unscored += int(n)
            else:
                scores[int(score)] = int(n)
        return scores, unscored

    def lead_summaries(self, company_ids: Collection[str]) -> dict[str, LeadSummary]:
        """For each company: its first-ranked person the engine works on, that person's main
        address status, and what its vendor calls cost. Three queries for a whole page."""
        ids = list(company_ids)
        if not ids:
            return {}
        people: dict[str, tuple[str, str | None, str | None]] = {}
        stmt = (
            select(ContactRow.company_id, ContactRow.id, ContactRow.full_name, ContactRow.title)
            .where(
                ContactRow.workspace_id == self._workspace_id,
                ContactRow.company_id.in_(ids),
                ContactRow.status.in_(_WORKED_ON),
            )
            .order_by(ContactRow.company_id, ContactRow.rank, ContactRow.created_at)
        )
        for company_id, contact_id, name, title in self._session.execute(stmt):
            people.setdefault(company_id, (contact_id, name, title))
        statuses: dict[str, str] = {}
        contact_ids = [p[0] for p in people.values()]
        if contact_ids:
            stmt_e = (
                select(ContactEmailRow.contact_id, ContactEmailRow.status)
                .where(
                    ContactEmailRow.workspace_id == self._workspace_id,
                    ContactEmailRow.contact_id.in_(contact_ids),
                )
                .order_by(ContactEmailRow.is_primary.desc(), ContactEmailRow.created_at.desc())
            )
            for contact_id, status in self._session.execute(stmt_e):
                statuses.setdefault(contact_id, status.value)
        costs = {
            company_id: int(cost)
            for company_id, cost in self._session.execute(
                select(
                    ProviderCallRow.company_id,
                    func.coalesce(func.sum(ProviderCallRow.credits_milli), 0),
                )
                .where(
                    ProviderCallRow.workspace_id == self._workspace_id,
                    ProviderCallRow.company_id.in_(ids),
                )
                .group_by(ProviderCallRow.company_id)
            )
        }
        out: dict[str, LeadSummary] = {}
        for company_id in ids:
            person = people.get(company_id)
            out[company_id] = LeadSummary(
                company_id,
                person[1] if person else None,
                person[2] if person else None,
                statuses.get(person[0]) if person else None,
                costs.get(company_id, 0),
            )
        return out
