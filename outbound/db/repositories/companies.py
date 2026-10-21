"""Companies: the lead, and the only place its status changes."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select

from outbound.db.models import CompanyRow
from outbound.db.repositories.base import ScopedRepository, snapshot
from outbound.db.types import utcnow
from outbound.domain.actors import SYSTEM
from outbound.domain.entities import Company
from outbound.domain.enums import CompanySource, CompanyStatus, EntityType, HoldReason
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


class CompanyRepository(ScopedRepository):
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

    def by_domain(self, domain: str) -> Company | None:
        stmt = select(CompanyRow).where(
            CompanyRow.workspace_id == self._workspace_id, CompanyRow.domain == domain.lower()
        )
        row = self._session.scalars(stmt).one_or_none()
        return snapshot(row, Company) if row else None

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
                or_(CompanyRow.next_action_at.is_(None), CompanyRow.next_action_at <= moment),
            )
            .order_by(CompanyRow.priority, CompanyRow.created_at, CompanyRow.id)
            .limit(limit)
        )
        return [snapshot(row, Company) for row in self._session.scalars(stmt)]

    def search(
        self,
        *,
        status: CompanyStatus | None = None,
        hold_reason: HoldReason | None = None,
        campaign_id: str | None = None,
        text: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Company], int]:
        """A page of companies, newest first, and how many match in all."""
        filters = [CompanyRow.workspace_id == self._workspace_id]
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
        stmt = (
            select(CompanyRow)
            .where(*filters)
            .order_by(CompanyRow.created_at.desc(), CompanyRow.id.desc())
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
        next_action_at: datetime | Unset | None = UNSET,
    ) -> Company:
        """Move a company to a new status through the state machine and log the move.

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
            row.attempts += 1
        else:
            row.failed_stage = None
            row.last_error = None
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
        self._events.append(EntityType.COMPANY, row.id, "status_changed", actor, detail)
        return snapshot(row, Company)

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
