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

from outbound.db.models import RunRow, WorkspacePlanRow, WorkspaceRow
from outbound.db.repositories.plans import PlanAdminRepository, PlatformSettingsRepository
from outbound.db.repositories.workspaces import WorkspaceRepository
from outbound.db.types import utcnow
from outbound.domain.enums import RunStatus, WorkspaceStatus


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


class PlatformUnitOfWork:
    session: Session

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._factory = session_factory

    def __enter__(self) -> Self:
        self.session = self._factory()
        self.workspaces = WorkspaceRepository(self.session)
        self.scheduler = SchedulerQueries(self.session)
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
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._factory = session_factory

    def __call__(self) -> PlatformUnitOfWork:
        return PlatformUnitOfWork(self._factory)
