"""Unit of work: one database session, one workspace, and every repository bound to both.

    with uow_factory(workspace_id) as uow:
        company = uow.companies.get(company_id)
        uow.companies.transition(...)
        uow.commit()

Leaving the block without ``commit`` rolls everything back.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any, Self

from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from outbound.db.errors import ConcurrencyConflict
from outbound.db.repositories.audit import ProviderCallRepository, RunRepository
from outbound.db.repositories.base import EventRepository
from outbound.db.repositories.companies import CompanyRepository
from outbound.db.repositories.contacts import (
    ConsentRepository,
    ContactEmailRepository,
    ContactRepository,
    NoteRepository,
)
from outbound.db.repositories.erasure import ErasureRepository
from outbound.db.repositories.imports import ImportRepository
from outbound.db.repositories.messages import MessageRepository
from outbound.db.repositories.policies import CountryPolicyRepository
from outbound.db.repositories.reports import ReportRepository
from outbound.db.repositories.suppressions import SuppressionRepository
from outbound.db.repositories.workspaces import (
    CampaignRepository,
    MailboxRepository,
    OwnWorkspaceRepository,
)
from outbound.domain.entities import Workspace


class UnitOfWork:
    session: Session

    def __init__(self, session_factory: sessionmaker[Session], workspace_id: str) -> None:
        self._factory = session_factory
        self.workspace_id = workspace_id

    def __enter__(self) -> Self:
        # Read by the session's ``after_begin`` listener: the row-level-security key.
        self.session = self._factory(info={"workspace_id": self.workspace_id})
        self.events = EventRepository(self.session, self.workspace_id)
        args = (self.session, self.workspace_id, self.events)
        self.companies = CompanyRepository(*args)
        self.contacts = ContactRepository(*args)
        self.emails = ContactEmailRepository(*args)
        self.notes = NoteRepository(*args)
        self.consents = ConsentRepository(*args)
        self.messages = MessageRepository(*args)
        self.imports = ImportRepository(*args)
        self.suppressions = SuppressionRepository(*args)
        self.policies = CountryPolicyRepository(*args)
        self.campaigns = CampaignRepository(*args)
        self.mailboxes = MailboxRepository(*args)
        self.runs = RunRepository(*args)
        self.calls = ProviderCallRepository(*args)
        self.erasure = ErasureRepository(*args)
        self.reports = ReportRepository(*args)
        self.own_workspace = OwnWorkspaceRepository(self.session, self.workspace_id)
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
        try:
            self.session.commit()
        except StaleDataError as error:
            self.session.rollback()
            raise ConcurrencyConflict("the row changed since it was read") from error

    def rollback(self) -> None:
        self.session.rollback()

    def workspace(self) -> Workspace | None:
        """This workspace's own row (sender profile and settings), read in this session."""
        return self.own_workspace.get()

    def workspace_settings(self) -> dict[str, Any]:
        """This workspace's settings (its own row only), for checks deep inside a stage."""
        workspace = self.workspace()
        return dict(workspace.settings) if workspace else {}


class UnitOfWorkFactory:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._factory = session_factory

    def __call__(self, workspace_id: str) -> UnitOfWork:
        return UnitOfWork(self._factory, workspace_id)
