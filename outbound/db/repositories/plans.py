"""Plans, overrides, credit grants and usage (Phase 6d).

Two views of the same tables. ``UsageRepository`` is the workspace's own (tenant unit of work):
it reads the plan, overrides and grants, counts this period's use, and writes one thing, a
charge. ``PlanAdminRepository`` is the platform's (platform unit of work): it changes the plan,
overrides, grants and access date of any workspace. The database enforces the split: the app
role may only read the first three tables.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from outbound.db.errors import ConcurrencyConflict, NotFound
from outbound.db.models import (
    CreditGrantRow,
    EntitlementOverrideRow,
    PlatformSettingsRow,
    UsageEventRow,
    WorkspacePlanRow,
)
from outbound.db.repositories.base import ScopedRepository
from outbound.db.types import utcnow
from outbound.domain.entitlements import Grant, Override, PlanAssignment
from outbound.domain.enums import UsageStep
from outbound.domain.platform_settings import PlatformSettings, from_json, to_json

SETTINGS_ID = "platform"


def _assignment(row: WorkspacePlanRow) -> PlanAssignment:
    return PlanAssignment(row.plan_code, row.started_at, row.access_until, row.note)


def _override(row: EntitlementOverrideRow) -> Override:
    return Override(
        key=row.key,
        value=(row.value or {}).get("value"),
        created_at=row.created_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        note=row.note,
        id=row.id,
    )


def _grant(row: CreditGrantRow) -> Grant:
    return Grant(
        step=row.step,
        amount=row.amount,
        created_at=row.created_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        note=row.note,
        id=row.id,
    )


class PlatformSettingsRepository:
    """The one settings row. Every role may read it; only the platform role may write it."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self) -> tuple[PlatformSettings, int]:
        """The settings and their version (0 when nothing was ever saved: the defaults)."""
        row = self._session.get(PlatformSettingsRow, SETTINGS_ID)
        if row is None:
            return PlatformSettings(), 0
        return from_json(row.data or {}), row.version

    def save(self, settings: PlatformSettings, *, expected_version: int) -> int:
        """Replace the settings if nobody saved since ``expected_version`` was read."""
        row = self._session.get(PlatformSettingsRow, SETTINGS_ID)
        if row is None:
            if expected_version != 0:
                raise ConcurrencyConflict("the settings changed since they were read")
            self._session.add(
                PlatformSettingsRow(id=SETTINGS_ID, data=to_json(settings), version=1)
            )
            self._session.flush()
            return 1
        if row.version != expected_version:
            raise ConcurrencyConflict("the settings changed since they were read")
        row.data = to_json(settings)
        row.version += 1
        row.updated_at = utcnow()
        self._session.flush()
        return row.version


class UsageRepository(ScopedRepository):
    """A workspace's plan, overrides, grants and use. Writes only charges."""

    def assignment(self) -> PlanAssignment | None:
        stmt = select(WorkspacePlanRow).where(WorkspacePlanRow.workspace_id == self._workspace_id)
        row = self._session.scalars(stmt).one_or_none()
        return _assignment(row) if row else None

    def overrides(self) -> list[Override]:
        stmt = (
            select(EntitlementOverrideRow)
            .where(EntitlementOverrideRow.workspace_id == self._workspace_id)
            .order_by(EntitlementOverrideRow.created_at)
        )
        return [_override(r) for r in self._session.scalars(stmt)]

    def grants(self) -> list[Grant]:
        stmt = (
            select(CreditGrantRow)
            .where(CreditGrantRow.workspace_id == self._workspace_id)
            .order_by(CreditGrantRow.created_at)
        )
        return [_grant(r) for r in self._session.scalars(stmt)]

    def used(self, start: datetime, end: datetime) -> dict[UsageStep, int]:
        """Charges made in ``[start, end)``, per step."""
        stmt = (
            select(UsageEventRow.step, func.count())
            .where(
                UsageEventRow.workspace_id == self._workspace_id,
                UsageEventRow.created_at >= start,
                UsageEventRow.created_at < end,
            )
            .group_by(UsageEventRow.step)
        )
        return {step: int(count) for step, count in self._session.execute(stmt)}

    def charged(self, step: UsageStep, company_id: str) -> bool:
        stmt = select(func.count()).where(
            UsageEventRow.workspace_id == self._workspace_id,
            UsageEventRow.step == step,
            UsageEventRow.company_id == company_id,
        )
        return bool(self._session.scalar(stmt))

    def charge(self, step: UsageStep, company_id: str) -> bool:
        """Charge ``step`` on a lead. False if it was charged already (not an error: a retry, a
        rerun or "research again" must not cost twice). ``rewrite`` is charged every time."""
        try:
            with self._session.begin_nested():
                self._session.add(
                    UsageEventRow(workspace_id=self._workspace_id, step=step, company_id=company_id)
                )
        except IntegrityError:
            return False
        return True


class PlanAdminRepository:
    """The platform's side: any workspace's plan, overrides, grants and access date."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # reads
    def assignment(self, workspace_id: str) -> PlanAssignment | None:
        row = self._plan_row(workspace_id)
        return _assignment(row) if row else None

    def overrides(self, workspace_id: str) -> list[Override]:
        stmt = (
            select(EntitlementOverrideRow)
            .where(EntitlementOverrideRow.workspace_id == workspace_id)
            .order_by(EntitlementOverrideRow.created_at)
        )
        return [_override(r) for r in self._session.scalars(stmt)]

    def grants(self, workspace_id: str) -> list[Grant]:
        stmt = (
            select(CreditGrantRow)
            .where(CreditGrantRow.workspace_id == workspace_id)
            .order_by(CreditGrantRow.created_at)
        )
        return [_grant(r) for r in self._session.scalars(stmt)]

    def used(self, workspace_id: str, start: datetime, end: datetime) -> dict[UsageStep, int]:
        stmt = (
            select(UsageEventRow.step, func.count())
            .where(
                UsageEventRow.workspace_id == workspace_id,
                UsageEventRow.created_at >= start,
                UsageEventRow.created_at < end,
            )
            .group_by(UsageEventRow.step)
        )
        return {step: int(count) for step, count in self._session.execute(stmt)}

    # writes
    def set_plan(
        self,
        workspace_id: str,
        plan_code: str,
        *,
        started_at: datetime | None = None,
        access_until: datetime | None = None,
        note: str = "",
    ) -> PlanAssignment:
        """Put the workspace on a plan. Changing plan keeps the period anchor and the access
        date unless new ones are given."""
        row = self._plan_row(workspace_id)
        if row is None:
            row = WorkspacePlanRow(
                workspace_id=workspace_id,
                plan_code=plan_code,
                started_at=started_at or utcnow(),
                access_until=access_until,
                note=note,
            )
            self._session.add(row)
        else:
            row.plan_code = plan_code
            if started_at is not None:
                row.started_at = started_at
            if access_until is not None:
                row.access_until = access_until
            if note:
                row.note = note
        self._session.flush()
        return _assignment(row)

    def set_access_until(self, workspace_id: str, until: datetime | None) -> PlanAssignment:
        row = self._plan_row(workspace_id)
        if row is None:
            raise NotFound(f"plan of workspace {workspace_id}")
        row.access_until = until
        self._session.flush()
        return _assignment(row)

    def add_override(
        self,
        workspace_id: str,
        key: str,
        value: int | bool | None,
        *,
        expires_at: datetime | None = None,
        note: str = "",
        set_by: str | None = None,
    ) -> Override:
        row = EntitlementOverrideRow(
            workspace_id=workspace_id, key=key, value={"value": value},
            expires_at=expires_at, note=note, set_by=set_by,
        )  # fmt: skip
        self._session.add(row)
        self._session.flush()
        return _override(row)

    def revoke_override(self, workspace_id: str, override_id: str) -> Override:
        row = self._session.get(EntitlementOverrideRow, override_id)
        if row is None or row.workspace_id != workspace_id:
            raise NotFound(f"override {override_id}")
        row.revoked_at = row.revoked_at or utcnow()
        self._session.flush()
        return _override(row)

    def add_grant(
        self,
        workspace_id: str,
        step: UsageStep,
        amount: int,
        *,
        expires_at: datetime | None = None,
        note: str = "",
        granted_by: str | None = None,
    ) -> Grant:
        row = CreditGrantRow(
            workspace_id=workspace_id, step=step, amount=amount,
            expires_at=expires_at, note=note, granted_by=granted_by,
        )  # fmt: skip
        self._session.add(row)
        self._session.flush()
        return _grant(row)

    def revoke_grant(self, workspace_id: str, grant_id: str) -> Grant:
        row = self._session.get(CreditGrantRow, grant_id)
        if row is None or row.workspace_id != workspace_id:
            raise NotFound(f"grant {grant_id}")
        row.revoked_at = row.revoked_at or utcnow()
        self._session.flush()
        return _grant(row)

    def _plan_row(self, workspace_id: str) -> WorkspacePlanRow | None:
        stmt = select(WorkspacePlanRow).where(WorkspacePlanRow.workspace_id == workspace_id)
        return self._session.scalars(stmt).one_or_none()


__all__ = ["SETTINGS_ID", "PlanAdminRepository", "PlatformSettingsRepository", "UsageRepository"]
