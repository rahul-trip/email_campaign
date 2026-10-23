"""The platform unit of work: the only way to read across workspaces.

Tenant code works inside one workspace through ``UnitOfWork``. A few jobs must look at every
workspace: resolving a workspace by name or slug, the scheduler's "which workspaces have work
due", and (later) the admin console. They use this, and import-linter keeps stages, the runner,
metering and tenant services from importing it. It writes platform data only: every change to
a workspace's own rows goes through that workspace's ``UnitOfWork``.
"""

from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy.orm import Session, sessionmaker

from outbound.db.repositories.workspaces import WorkspaceRepository


class PlatformUnitOfWork:
    session: Session

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._factory = session_factory

    def __enter__(self) -> Self:
        self.session = self._factory()
        self.workspaces = WorkspaceRepository(self.session)
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
