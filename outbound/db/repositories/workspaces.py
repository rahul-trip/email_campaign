"""Workspaces (the one unscoped table) and the campaigns inside them."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from outbound.db.models import CampaignRow, MailboxRow, WorkspaceRow
from outbound.db.repositories.base import ScopedRepository, snapshot
from outbound.domain.entities import Campaign, Workspace
from outbound.domain.enums import MailboxGateway, MailboxStatus


class WorkspaceRepository:
    """Not scoped: this is where scopes come from."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self, name: str, sender_profile: dict[str, Any], settings: dict[str, Any]
    ) -> Workspace:
        row = WorkspaceRow(name=name, sender_profile=sender_profile, settings=settings)
        self._session.add(row)
        self._session.flush()
        return snapshot(row, Workspace)

    def by_name(self, name: str) -> Workspace | None:
        row = self._session.scalars(select(WorkspaceRow).where(WorkspaceRow.name == name)).first()
        return snapshot(row, Workspace) if row else None

    def get(self, workspace_id: str) -> Workspace | None:
        row = self._session.get(WorkspaceRow, workspace_id)
        return snapshot(row, Workspace) if row else None

    def set_sender_profile(self, workspace_id: str, profile: dict[str, Any]) -> Workspace:
        row = self._session.get(WorkspaceRow, workspace_id)
        if row is None:
            raise LookupError(workspace_id)
        row.sender_profile = profile
        self._session.flush()
        return snapshot(row, Workspace)

    def set_settings(self, workspace_id: str, settings: dict[str, Any]) -> Workspace:
        row = self._session.get(WorkspaceRow, workspace_id)
        if row is None:
            raise LookupError(workspace_id)
        row.settings = settings
        self._session.flush()
        return snapshot(row, Workspace)

    def all(self) -> list[Workspace]:
        rows = self._session.scalars(select(WorkspaceRow).order_by(WorkspaceRow.created_at))
        return [snapshot(row, Workspace) for row in rows]


class CampaignRepository(ScopedRepository):
    def create(
        self,
        name: str,
        target_titles: list[str],
        *,
        icp_description: str | None = None,
        min_fit_score: int = 60,
        research_questions: list[str] | None = None,
        cadence_days: list[int] | None = None,
    ) -> Campaign:
        row = CampaignRow(
            workspace_id=self._workspace_id,
            name=name,
            target_titles=target_titles,
            icp_description=icp_description,
            min_fit_score=min_fit_score,
            research_questions=research_questions or [],
            cadence_days=cadence_days or [0, 3, 8],
        )
        self._session.add(row)
        self._session.flush()
        return snapshot(row, Campaign)

    def by_name(self, name: str) -> Campaign | None:
        stmt = select(CampaignRow).where(
            CampaignRow.workspace_id == self._workspace_id, CampaignRow.name == name
        )
        row = self._session.scalars(stmt).one_or_none()
        return snapshot(row, Campaign) if row else None

    def get(self, campaign_id: str) -> Campaign:
        return snapshot(self._row(CampaignRow, campaign_id), Campaign)

    def all(self) -> list[Campaign]:
        stmt = (
            select(CampaignRow)
            .where(CampaignRow.workspace_id == self._workspace_id)
            .order_by(CampaignRow.created_at)
        )
        return [snapshot(row, Campaign) for row in self._session.scalars(stmt)]

    def update(self, campaign_id: str, changes: dict[str, Any]) -> Campaign:
        allowed = {
            "name", "target_titles", "icp_description", "min_fit_score",
            "research_questions", "cadence_days",
        }  # fmt: skip
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"cannot change {sorted(unknown)}")
        row = self._row(CampaignRow, campaign_id)
        for name, value in changes.items():
            setattr(row, name, value)
        self._session.flush()
        return snapshot(row, Campaign)


@dataclass(frozen=True)
class MailboxView:
    id: str
    address: str
    gateway: MailboxGateway
    credentials_ref: str
    sending_domain: str
    dns_check: dict[str, Any] | None
    daily_cap: int
    status: MailboxStatus
    warmup_started_at: datetime | None


class MailboxRepository(ScopedRepository):
    def create(
        self,
        address: str,
        sending_domain: str,
        credentials_ref: str,
        *,
        gateway: MailboxGateway = MailboxGateway.IMAP,
        daily_cap: int = 10,
    ) -> MailboxView:
        row = MailboxRow(
            workspace_id=self._workspace_id,
            address=address.strip().lower(),
            gateway=gateway,
            credentials_ref=credentials_ref,
            sending_domain=sending_domain.strip().lower(),
            daily_cap=daily_cap,
        )
        self._session.add(row)
        self._session.flush()
        return self._view(row)

    def all(self) -> list[MailboxView]:
        stmt = (
            select(MailboxRow)
            .where(MailboxRow.workspace_id == self._workspace_id)
            .order_by(MailboxRow.created_at)
        )
        return [self._view(row) for row in self._session.scalars(stmt)]

    def get(self, mailbox_id: str) -> MailboxView:
        return self._view(self._row(MailboxRow, mailbox_id))

    def set_dns_check(self, mailbox_id: str, report: dict[str, Any]) -> MailboxView:
        row = self._row(MailboxRow, mailbox_id)
        row.dns_check = report
        self._session.flush()
        return self._view(row)

    @staticmethod
    def _view(row: MailboxRow) -> MailboxView:
        return MailboxView(
            row.id,
            row.address,
            row.gateway,
            row.credentials_ref,
            row.sending_domain,
            row.dns_check,
            row.daily_cap,
            row.status,
            row.warmup_started_at,
        )
