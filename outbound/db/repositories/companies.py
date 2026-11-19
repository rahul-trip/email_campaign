"""Companies: the lead, and the only place its status changes."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, and_, exists, func, or_, select

from outbound.db.models import CampaignRow, CompanyRow, LinkedInMessageRow
from outbound.db.repositories.base import ScopedRepository, snapshot
from outbound.db.types import utcnow
from outbound.domain.actors import SYSTEM
from outbound.domain.discovery import QUALIFIED
from outbound.domain.entities import Company
from outbound.domain.enums import (
    CampaignStatus,
    CompanySource,
    CompanyStatus,
    EntityType,
    FailureKind,
    HoldReason,
    LinkedInState,
    UsageStep,
)
from outbound.domain.outcomes import (
    ERROR_TRIES,
    OUTCOME_TRIES,
    SELF_RESOLVING_HOLDS,
    Bucket,
    bucket_of,
)
from outbound.domain.qualification import HOT_ABOVE
from outbound.domain.state_machines import COMPANY, STAGE_INPUT_STATUS


class Unset:
    """Marks "leave this field alone", since None is a real value for ``next_action_at``."""


UNSET = Unset()

# Fields callers may change through ``update_fields``. Status moves only via ``transition``.
EDITABLE_FIELDS = frozenset(
    {
        "name",
        "country_code",
        "legal_entity_type",
        "priority",
        "campaign_id",
        "fit_score",
        "fit_reason",
        "email_pattern",
        "research",
        "research_answers",
        "policy_decision",
        "policy_skip_from",
        "next_action_at",
    }
)


# What the leads list may be sorted by, and each column's natural direction.
def _bucket_filter(bucket: Bucket) -> ColumnElement[bool]:
    """The rows ``domain.outcomes.bucket_of`` puts in ``bucket`` (a test keeps the two equal)."""
    failed = CompanyRow.status == CompanyStatus.FAILED
    parked = CompanyRow.credit_wait_step.is_not(None)
    outcome = CompanyRow.failure_kind.in_((FailureKind.NO_PERSON, FailureKind.NO_EMAIL))
    gave_up = and_(failed, ~parked, outcome, CompanyRow.attempts >= OUTCOME_TRIES)
    hot = CompanyRow.fit_score > HOT_ABOVE
    # A LinkedIn message is written (or sent) for someone here: a way in, so not a failure.
    reachable = and_(
        failed,
        ~parked,
        exists().where(
            LinkedInMessageRow.company_id == CompanyRow.id,
            LinkedInMessageRow.state.in_((LinkedInState.DRAFTED, LinkedInState.SENT)),
        ),
    )
    ready = or_(CompanyRow.status == CompanyStatus.COPY_READY, reachable, and_(gave_up, hot))
    done = CompanyRow.status.in_(
        (
            CompanyStatus.APPROVED,
            CompanyStatus.IN_SEQUENCE,
            CompanyStatus.REPLIED,
            CompanyStatus.COMPLETED,
        )
    )
    screened = or_(
        CompanyRow.status.in_(
            (CompanyStatus.DISQUALIFIED, CompanyStatus.REJECTED, CompanyStatus.SUPPRESSED)
        ),
        and_(
            gave_up,
            ~reachable,
            or_(CompanyRow.fit_score.is_(None), CompanyRow.fit_score <= HOT_ABOVE),
        ),
    )
    stuck = and_(
        failed,
        ~parked,
        ~outcome,
        CompanyRow.attempts >= ERROR_TRIES,
    )
    decision = or_(
        and_(
            CompanyRow.status == CompanyStatus.HELD,
            CompanyRow.hold_reason.not_in(tuple(SELF_RESOLVING_HOLDS)),
        ),
        stuck,
    )
    if bucket is Bucket.READY:
        return ready
    if bucket is Bucket.DONE:
        return done
    if bucket is Bucket.SCREENED_OUT:
        return screened
    if bucket is Bucket.DECISION:
        return and_(~ready, ~done, ~screened, decision)
    return and_(~ready, ~done, ~screened, ~decision)


_SORTS: dict[str, tuple[Any, str]] = {
    "newest": (CompanyRow.created_at, "desc"),
    "fit": (CompanyRow.fit_score, "desc"),
    "updated": (CompanyRow.updated_at, "desc"),
    "name": (func.lower(func.coalesce(CompanyRow.name, CompanyRow.domain)), "asc"),
    "status": (CompanyRow.status, "asc"),
    "country": (CompanyRow.country_code, "asc"),
    "source": (CompanyRow.source, "asc"),
    "priority": (CompanyRow.priority, "asc"),
}
SORTABLE = tuple(_SORTS)


class CompanyRepository(ScopedRepository):
    def _in_a_live_campaign(self) -> Any:
        """A lead is worked on only while its campaign is the active one. A lead with no
        campaign (added by hand) is not held back."""
        active = select(CampaignRow.id).where(
            CampaignRow.workspace_id == self._workspace_id,
            CampaignRow.status == CampaignStatus.ACTIVE,
        )
        return or_(CompanyRow.campaign_id.is_(None), CompanyRow.campaign_id.in_(active))

    def create(
        self,
        *,
        domain: str,
        source: CompanySource,
        name: str | None = None,
        campaign_id: str | None = None,
        country_code: str | None = None,
        priority: int = 5,
        status: CompanyStatus = CompanyStatus.NEW,
        actor: str = SYSTEM,
    ) -> Company:
        row = CompanyRow(
            workspace_id=self._workspace_id,
            domain=domain.lower(),
            source=source,
            name=name,
            campaign_id=campaign_id,
            country_code=country_code.upper() if country_code else None,
            priority=priority,
            status=status,
            manual_fields=[],
        )
        self._session.add(row)
        self._session.flush()
        self._events.append(
            EntityType.COMPANY,
            row.id,
            "created",
            actor,
            {"domain": row.domain, "source": source.value, "status": status.value},
        )
        return snapshot(row, Company)

    def get(self, company_id: str) -> Company:
        return snapshot(self._row(CompanyRow, company_id), Company)

    def get_many(self, company_ids: Collection[str]) -> dict[str, Company]:
        """Several companies in one query, by id (a missing one is simply not in the answer)."""
        if not company_ids:
            return {}
        stmt = select(CompanyRow).where(
            CompanyRow.workspace_id == self._workspace_id, CompanyRow.id.in_(list(company_ids))
        )
        return {row.id: snapshot(row, Company) for row in self._session.scalars(stmt)}

    def by_domain(self, domain: str) -> Company | None:
        stmt = select(CompanyRow).where(
            CompanyRow.workspace_id == self._workspace_id, CompanyRow.domain == domain.lower()
        )
        row = self._session.scalars(stmt).one_or_none()
        return snapshot(row, Company) if row else None

    def qualified_domains(self, campaign_id: str, limit: int) -> list[str]:
        """The websites of this campaign's leads that passed the fit gate, best fit first:
        examples to find more like."""
        stmt = (
            select(CompanyRow.domain)
            .where(
                CompanyRow.workspace_id == self._workspace_id,
                CompanyRow.campaign_id == campaign_id,
                CompanyRow.status.in_(sorted(QUALIFIED)),
            )
            .order_by(CompanyRow.fit_score.desc().nulls_last(), CompanyRow.created_at)
            .limit(limit)
        )
        return list(self._session.scalars(stmt))

    def known_domains(self) -> set[str]:
        stmt = select(CompanyRow.domain).where(CompanyRow.workspace_id == self._workspace_id)
        return set(self._session.scalars(stmt))

    def due(self, status: CompanyStatus, limit: int, now: datetime | None = None) -> list[Company]:
        """Companies waiting in ``status`` whose scheduled time (if any) has arrived."""
        moment = now or utcnow()
        stmt = (
            select(CompanyRow)
            .where(
                CompanyRow.workspace_id == self._workspace_id,
                CompanyRow.status == status,
                CompanyRow.credit_wait_step.is_(
                    None
                ),  # waiting for credits: not due until released
                or_(CompanyRow.next_action_at.is_(None), CompanyRow.next_action_at <= moment),
                self._in_a_live_campaign(),  # a paused campaign's leads wait
            )
            .order_by(CompanyRow.priority, CompanyRow.created_at, CompanyRow.id)
            .limit(limit)
        )
        return [snapshot(row, Company) for row in self._session.scalars(stmt)]

    def any_due(self, statuses: list[CompanyStatus], now: datetime | None = None) -> bool:
        """Whether any company waits in one of ``statuses`` with its time arrived."""
        moment = now or utcnow()
        stmt = select(CompanyRow.id).where(
            CompanyRow.workspace_id == self._workspace_id,
            CompanyRow.status.in_(statuses),
            CompanyRow.credit_wait_step.is_(None),
            or_(CompanyRow.next_action_at.is_(None), CompanyRow.next_action_at <= moment),
            self._in_a_live_campaign(),
        )
        return self._session.scalars(stmt.limit(1)).first() is not None

    def count_in(self, statuses: Collection[CompanyStatus], campaign_id: str) -> int:
        """How many of a campaign's companies are in one of ``statuses`` and not waiting for
        credits."""
        stmt = select(func.count()).where(
            CompanyRow.workspace_id == self._workspace_id,
            CompanyRow.campaign_id == campaign_id,
            CompanyRow.status.in_(statuses),
            CompanyRow.credit_wait_step.is_(None),
        )
        return int(self._session.scalar(stmt) or 0)

    def search(
        self,
        *,
        status: CompanyStatus | None = None,
        hold_reason: HoldReason | None = None,
        campaign_id: str | None = None,
        text: str | None = None,
        waiting_for_credits: bool | None = None,
        min_fit: int | None = None,
        hot: bool | None = None,
        source: CompanySource | None = None,
        country: str | None = None,
        bucket: Bucket | None = None,
        sort: str = "newest",
        direction: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Company], int]:
        """A page of companies and how many match in all. ``sort`` names a column (``newest`` is
        the date added; also ``fit``, ``updated``, ``name``, ``status``, ``country``, ``source``,
        ``priority``); ``direction`` is ``asc`` or ``desc``, else the column's natural order
        (newest, best fit and latest change first; names and the rest A to Z). Empty values go
        last either way."""
        filters = [CompanyRow.workspace_id == self._workspace_id]
        if min_fit is not None:
            filters.append(CompanyRow.fit_score >= min_fit)
        if hot is not None:
            # A hot lead scores above 80 (domain.qualification.HOT_ABOVE); unscored is neither.
            filters.append(
                CompanyRow.fit_score > HOT_ABOVE if hot else CompanyRow.fit_score <= HOT_ABOVE
            )
        if source is not None:
            filters.append(CompanyRow.source == source)
        if country:
            filters.append(func.upper(CompanyRow.country_code) == country.strip().upper())
        if waiting_for_credits is not None:
            parked = CompanyRow.credit_wait_step.is_not(None)
            filters.append(parked if waiting_for_credits else ~parked)
        if bucket is not None:
            filters.append(_bucket_filter(bucket))
        if status is not None:
            filters.append(CompanyRow.status == status)
        if hold_reason is not None:
            filters.append(CompanyRow.hold_reason == hold_reason)
        if campaign_id is not None:
            filters.append(CompanyRow.campaign_id == campaign_id)
        if text:
            like = f"%{text.strip().lower()}%"
            filters.append(
                or_(
                    func.lower(CompanyRow.domain).like(like), func.lower(CompanyRow.name).like(like)
                )
            )
        total = self._session.scalar(select(func.count()).select_from(CompanyRow).where(*filters))
        column, natural = _SORTS.get(sort, _SORTS["newest"])
        descending = (direction or natural) == "desc"
        key = column.desc() if descending else column.asc()
        order: tuple[Any, ...] = (key.nulls_last(), CompanyRow.created_at.desc())
        stmt = (
            select(CompanyRow)
            .where(*filters)
            .order_by(*order, CompanyRow.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return [snapshot(row, Company) for row in self._session.scalars(stmt)], int(total or 0)

    def due_held(
        self, reason: HoldReason, limit: int, now: datetime | None = None
    ) -> list[Company]:
        """Held companies waiting for ``reason`` whose wake-up time has arrived."""
        moment = now or utcnow()
        stmt = (
            select(CompanyRow)
            .where(
                CompanyRow.workspace_id == self._workspace_id,
                CompanyRow.status == CompanyStatus.HELD,
                CompanyRow.hold_reason == reason,
                or_(CompanyRow.next_action_at.is_(None), CompanyRow.next_action_at <= moment),
            )
            .order_by(CompanyRow.priority, CompanyRow.created_at, CompanyRow.id)
            .limit(limit)
        )
        return [snapshot(row, Company) for row in self._session.scalars(stmt)]

    def count_by_status(self) -> dict[CompanyStatus, int]:
        stmt = select(CompanyRow.status).where(CompanyRow.workspace_id == self._workspace_id)
        counts: dict[CompanyStatus, int] = {}
        for status in self._session.scalars(stmt):
            counts[status] = counts.get(status, 0) + 1
        return counts

    def count_buckets(self) -> dict[Bucket, int]:
        """How many leads are in each bucket (``domain.outcomes``)."""
        stmt = select(
            CompanyRow.id,
            CompanyRow.status,
            CompanyRow.hold_reason,
            CompanyRow.failure_kind,
            CompanyRow.attempts,
            CompanyRow.fit_score,
            CompanyRow.credit_wait_step,
        ).where(CompanyRow.workspace_id == self._workspace_id)
        counts = dict.fromkeys(Bucket, 0)
        reachable = self.with_linkedin_messages(None)
        for company_id, status, hold, kind, attempts, fit, parked in self._session.execute(stmt):
            bucket = bucket_of(
                status,
                hold_reason=hold,
                failure_kind=kind,
                attempts=attempts,
                fit_score=fit,
                waiting_for_credit=parked is not None,
                has_linkedin=company_id in reachable,
            )
            counts[bucket] += 1
        return counts

    def with_linkedin_messages(self, company_ids: Collection[str] | None) -> set[str]:
        """Which of these leads (all of them for ``None``) have a LinkedIn message written or
        sent for someone there."""
        stmt = (
            select(LinkedInMessageRow.company_id)
            .where(
                LinkedInMessageRow.workspace_id == self._workspace_id,
                LinkedInMessageRow.state.in_((LinkedInState.DRAFTED, LinkedInState.SENT)),
            )
            .distinct()
        )
        if company_ids is not None:
            stmt = stmt.where(LinkedInMessageRow.company_id.in_(list(company_ids)))
        return set(self._session.scalars(stmt))

    def transition(
        self,
        company_id: str,
        to: CompanyStatus,
        *,
        expected_version: int,
        actor: str = SYSTEM,
        reason: str | None = None,
        hold_reason: HoldReason | None = None,
        failed_stage: str | None = None,
        last_error: str | None = None,
        failure_kind: FailureKind = FailureKind.ERROR,
        next_action_at: datetime | Unset | None = UNSET,
        run_id: str | None = None,
        vendor_wait: bool = False,
    ) -> Company:
        """Move a company to a new status through the state machine and log the move.

        ``vendor_wait`` marks a failure that is a vendor's, not the lead's (no one could answer):
        it is not counted as an attempt, and the attempts so far are forgiven, so the lead
        keeps being retried until a vendor answers.

        ``run_id`` is recorded on the event when a run made the move, so a run can list what it
        did to each lead.

        Moving to ``held`` needs a ``hold_reason``; moving to ``failed`` needs a known
        ``failed_stage``. Leaving either state clears its detail columns.
        """
        row = self._row(CompanyRow, company_id)
        self._check_version(row, expected_version)
        COMPANY.check(row.status, to)
        if to is CompanyStatus.HELD and hold_reason is None:
            raise ValueError("a hold needs a hold_reason")
        if to is CompanyStatus.FAILED and failed_stage not in STAGE_INPUT_STATUS:
            raise ValueError(f"failed_stage must be one of {sorted(STAGE_INPUT_STATUS)}")

        previous = row.status
        row.status = to
        row.hold_reason = hold_reason if to is CompanyStatus.HELD else None
        if to is CompanyStatus.FAILED:
            row.failed_stage = failed_stage
            row.last_error = last_error
            row.failure_kind = failure_kind
            row.attempts = 0 if vendor_wait else row.attempts + 1
        else:
            row.failed_stage = None
            row.last_error = None
            row.failure_kind = None
        if not isinstance(next_action_at, Unset):
            row.next_action_at = next_action_at
        self._flush()

        detail: dict[str, Any] = {"from": previous.value, "to": to.value}
        if reason:
            detail["reason"] = reason
        if row.hold_reason:
            detail["hold_reason"] = row.hold_reason.value
        if row.failed_stage:
            detail["failed_stage"] = row.failed_stage
            detail["error"] = last_error
            detail["kind"] = failure_kind.value
        if run_id:
            detail["run_id"] = run_id
        self._events.append(EntityType.COMPANY, row.id, "status_changed", actor, detail)
        return snapshot(row, Company)

    def wait_for_credit(self, company_id: str, step: UsageStep) -> bool:
        """Park the lead where it is until a credit for ``step`` exists. True the first time;
        asking again for the same step changes nothing and records nothing."""
        row = self._row(CompanyRow, company_id)
        if row.credit_wait_step is step:
            return False
        row.credit_wait_step = step
        self._flush()
        self._events.append(
            EntityType.COMPANY, row.id, "waiting_for_credits", SYSTEM, {"step": step.value}
        )
        return True

    def waiting_for_credits(self, limit: int = 1000) -> list[Company]:
        """Leads parked for a credit, the one waiting longest first."""
        stmt = (
            select(CompanyRow)
            .where(
                CompanyRow.workspace_id == self._workspace_id,
                CompanyRow.credit_wait_step.is_not(None),
            )
            .order_by(CompanyRow.updated_at, CompanyRow.id)
            .limit(limit)
        )
        return [snapshot(row, Company) for row in self._session.scalars(stmt)]

    def release_credit_wait(self, company_id: str, actor: str = SYSTEM) -> UsageStep | None:
        """Let a waiting lead continue. Returns the step it waited on, or None if it was not
        waiting."""
        row = self._row(CompanyRow, company_id)
        step = row.credit_wait_step
        if step is None:
            return None
        row.credit_wait_step = None
        self._flush()
        self._events.append(EntityType.COMPANY, row.id, "resumed", actor, {"step": step.value})
        return step

    def set_skip_directory(self, company_id: str, skip: bool, *, actor: str) -> None:
        """Find this lead's emails with the vendors (True) or the shared directory (False)."""
        row = self._row(CompanyRow, company_id)
        if row.skip_directory != skip:
            row.skip_directory = skip
            self._flush()
            self._events.append(EntityType.COMPANY, row.id, "skip_directory", actor, {"skip": skip})

    def update_fields(
        self,
        company_id: str,
        changes: Mapping[str, Any],
        *,
        actor: str,
        expected_version: int,
    ) -> Company:
        """Change fields. The operator's values are protected from the engine; see base."""
        row = self._row(CompanyRow, company_id)
        self._check_version(row, expected_version)
        if changes.get("country_code"):
            changes = {**changes, "country_code": str(changes["country_code"]).upper()}
        self._apply_changes(
            row, changes, editable=EDITABLE_FIELDS, actor=actor, entity_type=EntityType.COMPANY
        )
        self._flush()
        return snapshot(row, Company)
