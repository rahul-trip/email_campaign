"""The platform unit of work: the only way to read across workspaces.

Tenant code works inside one workspace through ``UnitOfWork``. A few jobs must look at every
workspace: resolving a workspace by name or slug, the scheduler's "which workspaces have work
due", and (later) the admin console. They use this, and import-linter keeps stages, the runner,
metering and tenant services from importing it. It writes platform data only: every change to
a workspace's own rows goes through that workspace's ``UnitOfWork``.
"""

from __future__ import annotations

from datetime import datetime
from types import TracebackType
from typing import Self

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from outbound.db.crypto import Keyring
from outbound.db.identity import AuditRepository
from outbound.db.models import (
    CompanyRow,
    MailboxRow,
    ProviderCallRow,
    RunRow,
    UsageEventRow,
    WorkspacePlanRow,
    WorkspaceRow,
)
from outbound.db.repositories.directory import DirectoryAdminRepository
from outbound.db.repositories.plans import PlanAdminRepository, PlatformSettingsRepository
from outbound.db.repositories.vendors import VendorKeyRepository
from outbound.db.repositories.workspaces import WorkspaceRepository
from outbound.db.types import utcnow
from outbound.domain.enums import MailboxStatus, RunStatus, UsageStep, WorkspaceStatus


class SchedulerQueries:
    """What the worker needs to know across workspaces: ids only, never anyone's rows."""

    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _may_run(now: datetime) -> ColumnElement[bool]:
        """Active, and not past the access date its plan gives it (no plan row: no end)."""
        return and_(
            WorkspaceRow.status == WorkspaceStatus.ACTIVE,
            or_(WorkspacePlanRow.access_until.is_(None), WorkspacePlanRow.access_until > now),
        )

    def active_workspaces(self, now: datetime | None = None) -> list[str]:
        """Workspaces whose engine may run: active, with access (paused, suspended, deleted and
        expired ones may not)."""
        stmt = (
            select(WorkspaceRow.id)
            .outerjoin(WorkspacePlanRow, WorkspacePlanRow.workspace_id == WorkspaceRow.id)
            .where(self._may_run(now or utcnow()))
            .order_by(WorkspaceRow.id)
        )
        return list(self._session.scalars(stmt))

    def with_queued_runs(self, now: datetime | None = None) -> list[str]:
        """Workspaces that may run and have a queued run, the one waiting longest first."""
        stmt = (
            select(RunRow.workspace_id)
            .join(WorkspaceRow, WorkspaceRow.id == RunRow.workspace_id)
            .outerjoin(WorkspacePlanRow, WorkspacePlanRow.workspace_id == WorkspaceRow.id)
            .where(RunRow.status == RunStatus.QUEUED, self._may_run(now or utcnow()))
            .group_by(RunRow.workspace_id)
            .order_by(func.min(RunRow.created_at))
        )
        return list(self._session.scalars(stmt))

    def with_stale_runs(self, cutoff: datetime) -> list[str]:
        """Workspaces with a running run and no heartbeat since ``cutoff``."""
        stmt = (
            select(RunRow.workspace_id)
            .where(
                RunRow.status == RunStatus.RUNNING,
                or_(
                    RunRow.heartbeat_at < cutoff,
                    RunRow.heartbeat_at.is_(None)
                    & (RunRow.started_at.is_(None) | (RunRow.started_at < cutoff)),
                ),
            )
            .distinct()
        )
        return list(self._session.scalars(stmt))


def _spend() -> ColumnElement[int]:
    return func.coalesce(func.sum(ProviderCallRow.cost_micro_usd), 0)


class AdminQueries:
    """Figures across workspaces for the admin console: counts and sums, never anyone's rows
    of content (no names, no addresses, no email text)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def spend(self, start: datetime, end: datetime) -> dict[str, int]:
        """Vendor spend per workspace in ``[start, end)``, in micro-USD."""
        stmt = (
            select(
                ProviderCallRow.workspace_id,
                func.coalesce(func.sum(ProviderCallRow.cost_micro_usd), 0),
            )
            .where(ProviderCallRow.created_at >= start, ProviderCallRow.created_at < end)
            .group_by(ProviderCallRow.workspace_id)
        )
        return {ws: int(total) for ws, total in self._session.execute(stmt)}

    def spend_by_provider(self, start: datetime, end: datetime) -> dict[str, int]:
        stmt = (
            select(
                ProviderCallRow.provider, func.coalesce(func.sum(ProviderCallRow.cost_micro_usd), 0)
            )
            .where(ProviderCallRow.created_at >= start, ProviderCallRow.created_at < end)
            .group_by(ProviderCallRow.provider)
        )
        return {name: int(total) for name, total in self._session.execute(stmt)}

    def leads_added(self, start: datetime, end: datetime) -> int:
        """New leads (manual and discovered) charged in ``[start, end)``, all workspaces."""
        stmt = select(func.count()).where(
            UsageEventRow.step.in_((UsageStep.MANUAL, UsageStep.DISCOVERY)),
            UsageEventRow.created_at >= start,
            UsageEventRow.created_at < end,
        )
        return int(self._session.scalar(stmt) or 0)

    def drafts_made(self, start: datetime, end: datetime) -> int:
        stmt = select(func.count()).where(
            UsageEventRow.step == UsageStep.DELIVER,
            UsageEventRow.created_at >= start,
            UsageEventRow.created_at < end,
        )
        return int(self._session.scalar(stmt) or 0)

    def waiting_leads(self) -> dict[str, int]:
        """Leads parked for a credit, per workspace."""
        stmt = (
            select(CompanyRow.workspace_id, func.count())
            .where(CompanyRow.credit_wait_step.is_not(None))
            .group_by(CompanyRow.workspace_id)
        )
        return {ws: int(n) for ws, n in self._session.execute(stmt)}

    def mailboxes(self) -> dict[str, tuple[int, int]]:
        """(mailboxes, mailboxes needing attention) per workspace."""
        stmt = select(MailboxRow.workspace_id, MailboxRow.status)
        found: dict[str, tuple[int, int]] = {}
        for ws, status in self._session.execute(stmt):
            total, bad = found.get(ws, (0, 0))
            found[ws] = (
                total + 1,
                bad + (status in (MailboxStatus.ERROR, MailboxStatus.NEEDS_RECONNECT)),
            )
        return found

    def last_activity(self) -> dict[str, datetime]:
        stmt = select(CompanyRow.workspace_id, func.max(CompanyRow.updated_at)).group_by(
            CompanyRow.workspace_id
        )
        return {ws: when for ws, when in self._session.execute(stmt) if when is not None}

    def lead_counts(self) -> dict[str, int]:
        stmt = select(CompanyRow.workspace_id, func.count()).group_by(CompanyRow.workspace_id)
        return {ws: int(n) for ws, n in self._session.execute(stmt)}


class PlatformUnitOfWork:
    session: Session

    def __init__(
        self, session_factory: sessionmaker[Session], keyring: Keyring | None = None
    ) -> None:
        self._factory = session_factory
        self._keyring = keyring or Keyring({})

    def __enter__(self) -> Self:
        self.session = self._factory()
        self.vendor_keys = VendorKeyRepository(self.session, self._keyring)
        self.directory = DirectoryAdminRepository(self.session)
        self.workspaces = WorkspaceRepository(self.session)
        self.scheduler = SchedulerQueries(self.session)
        self.figures = AdminQueries(self.session)
        self.audit = AuditRepository(self.session)
        self.plans = PlanAdminRepository(self.session)
        self.settings = PlatformSettingsRepository(self.session)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            if exc_type is not None:
                self.session.rollback()
        finally:
            self.session.close()

    def commit(self) -> None:
        self.session.commit()


class PlatformUnitOfWorkFactory:
    def __init__(
        self, session_factory: sessionmaker[Session], keyring: Keyring | None = None
    ) -> None:
        self._factory = session_factory
        self._keyring = keyring

    def __call__(self) -> PlatformUnitOfWork:
        return PlatformUnitOfWork(self._factory, self._keyring)
