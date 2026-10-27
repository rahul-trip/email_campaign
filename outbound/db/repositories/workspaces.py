"""Workspaces and the campaigns, mailboxes and credentials inside them.

``WorkspaceRepository`` sees every workspace and is reached only through the platform unit of
work. A tenant unit of work holds ``OwnWorkspaceRepository``, which sees its own row only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from outbound.db.crypto import Keyring, Sealed, associated_data
from outbound.db.errors import NotFound
from outbound.db.models import CampaignRow, CredentialRow, MailboxRow, MessageRow, WorkspaceRow
from outbound.db.repositories.base import EventRepository, ScopedRepository, snapshot
from outbound.db.types import utcnow
from outbound.domain.entities import Campaign, Workspace
from outbound.domain.enums import (
    CredentialPurpose,
    MailboxGateway,
    MailboxStatus,
    WorkspaceStatus,
)
from outbound.domain.ids import new_id
from outbound.domain.join_codes import new_join_code, normalise_join_code
from outbound.domain.slugs import unique_slug
from outbound.domain.state_machines import WORKSPACE


class WorkspaceRepository:
    """Not scoped: this is where scopes come from."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        name: str,
        sender_profile: dict[str, Any],
        settings: dict[str, Any],
        *,
        slug: str | None = None,
    ) -> Workspace:
        """A new workspace. Its slug comes from the name unless given, made unique."""
        taken = set(self._session.scalars(select(WorkspaceRow.slug)))
        if slug is not None and slug in taken:
            raise ValueError(f"the address {slug!r} is taken")
        codes = set(self._session.scalars(select(WorkspaceRow.join_code)))
        code = new_join_code()
        while code in codes:
            code = new_join_code()
        row = WorkspaceRow(
            name=name,
            slug=slug or unique_slug(name, taken),
            join_code=code,
            sender_profile=sender_profile,
            settings=settings,
        )
        self._session.add(row)
        self._session.flush()
        return snapshot(row, Workspace)

    def by_slug(self, slug: str) -> Workspace | None:
        stmt = select(WorkspaceRow).where(WorkspaceRow.slug == slug)
        row = self._session.scalars(stmt).one_or_none()
        return snapshot(row, Workspace) if row else None

    def by_join_code(self, code: str) -> Workspace | None:
        stmt = select(WorkspaceRow).where(WorkspaceRow.join_code == normalise_join_code(code))
        row = self._session.scalars(stmt).one_or_none()
        return snapshot(row, Workspace) if row else None

    def new_join_code(self, workspace_id: str) -> Workspace:
        """Replace the code (for example when it was shared too widely)."""
        row = self._session.get(WorkspaceRow, workspace_id)
        if row is None:
            raise LookupError(workspace_id)
        taken = set(self._session.scalars(select(WorkspaceRow.join_code)))
        code = new_join_code()
        while code in taken:
            code = new_join_code()
        row.join_code = code
        self._session.flush()
        return snapshot(row, Workspace)

    def by_name(self, name: str) -> Workspace | None:
        """The oldest workspace with this name. Names may repeat: prefer ``by_slug``."""
        stmt = (
            select(WorkspaceRow)
            .where(WorkspaceRow.name == name)
            .order_by(WorkspaceRow.id)  # UUIDv7: the oldest first
        )
        row = self._session.scalars(stmt).first()
        return snapshot(row, Workspace) if row else None

    def find(self, ref: str) -> Workspace | None:
        """A workspace by slug, or else by name (how the CLI and settings name one)."""
        return self.by_slug(ref) or self.by_name(ref)

    def set_status(
        self, workspace_id: str, status: WorkspaceStatus, *, deletion_due_at: datetime | None = None
    ) -> Workspace:
        """Move a workspace through its lifecycle; illegal moves are refused."""
        row = self._session.get(WorkspaceRow, workspace_id)
        if row is None:
            raise LookupError(workspace_id)
        WORKSPACE.check(row.status, status)
        row.status = status
        row.deletion_due_at = (
            deletion_due_at if status is WorkspaceStatus.PENDING_DELETION else None
        )
        self._session.flush()
        return snapshot(row, Workspace)

    def rename(self, workspace_id: str, name: str, slug: str) -> Workspace:
        """A new name and address; the slug must be free (or already this workspace's)."""
        row = self._session.get(WorkspaceRow, workspace_id)
        if row is None:
            raise LookupError(workspace_id)
        holder = self.by_slug(slug)
        if holder is not None and holder.id != workspace_id:
            raise ValueError(f"the address {slug!r} is taken")
        row.name, row.slug = name, slug
        self._session.flush()
        return snapshot(row, Workspace)

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


class OwnWorkspaceRepository:
    """The one workspace a tenant unit of work belongs to: its own row, nothing else."""

    def __init__(self, session: Session, workspace_id: str) -> None:
        self._session = session
        self._workspace_id = workspace_id

    def get(self) -> Workspace | None:
        row = self._own()
        return snapshot(row, Workspace) if row else None

    def set_sender_profile(self, profile: dict[str, Any]) -> Workspace:
        row = self._required()
        row.sender_profile = profile
        self._session.flush()
        return snapshot(row, Workspace)

    def set_settings(self, settings: dict[str, Any]) -> Workspace:
        row = self._required()
        row.settings = settings
        self._session.flush()
        return snapshot(row, Workspace)

    def _own(self) -> WorkspaceRow | None:
        stmt = select(WorkspaceRow).where(WorkspaceRow.id == self._workspace_id)
        return self._session.scalars(stmt).one_or_none()

    def _required(self) -> WorkspaceRow:
        row = self._own()
        if row is None:
            raise NotFound(f"workspace {self._workspace_id}")
        return row


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
            "research_questions", "cadence_days", "mailbox_id",
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
    credentials_ref: str | None
    sending_domain: str
    dns_check: dict[str, Any] | None
    daily_cap: int
    status: MailboxStatus
    warmup_started_at: datetime | None
    owner_user_id: str | None = None
    is_default: bool = False
    sender: dict[str, Any] | None = None
    connection: dict[str, Any] | None = None
    last_checked_at: datetime | None = None


class MailboxRepository(ScopedRepository):
    def create(
        self,
        address: str,
        sending_domain: str,
        credentials_ref: str | None = None,
        *,
        gateway: MailboxGateway = MailboxGateway.IMAP,
        daily_cap: int = 10,
        owner_user_id: str | None = None,
        connection: dict[str, Any] | None = None,
        sender: dict[str, Any] | None = None,
        is_default: bool | None = None,
    ) -> MailboxView:
        """A mailbox. The first one in a workspace becomes its default sender."""
        if is_default is None:
            is_default = self.default() is None
        if is_default:
            self._clear_default()
        row = MailboxRow(
            workspace_id=self._workspace_id,
            address=address.strip().lower(),
            gateway=gateway,
            credentials_ref=credentials_ref,
            sending_domain=sending_domain.strip().lower(),
            daily_cap=daily_cap,
            owner_user_id=owner_user_id,
            connection=connection,
            sender=sender,
            is_default=is_default,
        )
        self._session.add(row)
        self._session.flush()
        return self._view(row)

    def by_address(self, address: str) -> MailboxView | None:
        stmt = select(MailboxRow).where(
            MailboxRow.workspace_id == self._workspace_id,
            MailboxRow.address == address.strip().lower(),
        )
        row = self._session.scalars(stmt).one_or_none()
        return self._view(row) if row else None

    def default(self) -> MailboxView | None:
        """The workspace's default sender."""
        stmt = select(MailboxRow).where(
            MailboxRow.workspace_id == self._workspace_id, MailboxRow.is_default.is_(True)
        )
        row = self._session.scalars(stmt).one_or_none()
        return self._view(row) if row else None

    def update(self, mailbox_id: str, **fields: Any) -> MailboxView:
        """Change ``credentials_ref``, ``connection``, ``sender``, ``status``, ``daily_cap``,
        ``gateway`` or ``last_checked_at``."""
        allowed = {
            "credentials_ref",
            "connection",
            "sender",
            "status",
            "daily_cap",
            "gateway",
            "last_checked_at",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"cannot change {sorted(unknown)}")
        row = self._row(MailboxRow, mailbox_id)
        for name, value in fields.items():
            setattr(row, name, value)
        self._session.flush()
        return self._view(row)

    def make_default(self, mailbox_id: str) -> MailboxView:
        row = self._row(MailboxRow, mailbox_id)
        self._clear_default()
        row.is_default = True
        self._session.flush()
        return self._view(row)

    def delete(self, mailbox_id: str) -> None:
        """Remove a mailbox. Campaigns that sent from it fall back to the default; the messages
        it drafted keep their history but no longer point at it."""
        row = self._row(MailboxRow, mailbox_id)
        self._session.execute(
            update(CampaignRow)
            .where(CampaignRow.workspace_id == self._workspace_id, CampaignRow.mailbox_id == row.id)
            .values(mailbox_id=None)
            .execution_options(synchronize_session=False)
        )
        self._session.execute(
            update(MessageRow)
            .where(MessageRow.workspace_id == self._workspace_id, MessageRow.mailbox_id == row.id)
            .values(mailbox_id=None)
            .execution_options(synchronize_session=False)
        )
        was_default = row.is_default
        self._session.delete(row)
        self._session.flush()
        if was_default:
            remaining = self._session.scalars(
                select(MailboxRow)
                .where(MailboxRow.workspace_id == self._workspace_id)
                .order_by(MailboxRow.created_at)
            ).first()
            if remaining is not None:
                remaining.is_default = True
                self._session.flush()

    def _clear_default(self) -> None:
        self._session.execute(
            update(MailboxRow)
            .where(MailboxRow.workspace_id == self._workspace_id, MailboxRow.is_default.is_(True))
            .values(is_default=False)
            .execution_options(synchronize_session=False)
        )
        self._session.flush()

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
            row.owner_user_id,
            row.is_default,
            dict(row.sender) if row.sender else None,
            dict(row.connection) if row.connection else None,
            row.last_checked_at,
        )


@dataclass(frozen=True)
class Credential:
    """A stored secret's description; the secret itself only comes from ``reveal``."""

    id: str
    name: str
    purpose: CredentialPurpose
    version: int
    expires_at: datetime | None
    details: dict[str, Any]
    updated_at: datetime


class CredentialRepository(ScopedRepository):
    """This workspace's secrets, sealed with the keyring on the way in and opened on the way out.

    A refresh token that rotates is replaced with ``swap``: it writes only if the row is still
    at the version the caller read, so two refreshes racing cannot lose a token.
    """

    def __init__(
        self, session: Session, workspace_id: str, events: EventRepository, keyring: Keyring
    ) -> None:
        super().__init__(session, workspace_id, events)
        self._keyring = keyring

    def put(
        self,
        name: str,
        purpose: CredentialPurpose,
        secret: str,
        *,
        expires_at: datetime | None = None,
        details: dict[str, Any] | None = None,
    ) -> Credential:
        """Store a secret under ``name``, replacing any there (its version goes up)."""
        row = self._find(name)
        if row is None:
            row = CredentialRow(id=new_id(), workspace_id=self._workspace_id, name=name, version=0)
            self._session.add(row)
        row.purpose = purpose
        self._seal(row, secret)
        row.version += 1
        row.expires_at = expires_at
        row.details = details or {}
        self._session.flush()
        return self._view(row)

    def get(self, name: str) -> Credential | None:
        row = self._find(name)
        return self._view(row) if row else None

    def reveal(self, name: str) -> tuple[Credential, str]:
        row = self._find(name)
        if row is None:
            raise NotFound(f"credential {name}")
        sealed = Sealed(row.key_version, row.nonce, row.ciphertext)
        return self._view(row), self._keyring.open(
            sealed, associated_data(row.workspace_id, row.id)
        )

    def swap(
        self, name: str, expected_version: int, secret: str, *, expires_at: datetime | None = None
    ) -> bool:
        """Replace the secret only if nobody else did since ``expected_version`` was read."""
        row = self._find(name)
        if row is None or row.version != expected_version:
            return False
        sealed = self._keyring.seal(secret, associated_data(row.workspace_id, row.id))
        changed = self._session.execute(
            update(CredentialRow)
            .where(
                CredentialRow.id == row.id,
                CredentialRow.workspace_id == self._workspace_id,
                CredentialRow.version == expected_version,
            )
            .values(
                key_version=sealed.key_version,
                nonce=sealed.nonce,
                ciphertext=sealed.ciphertext,
                version=expected_version + 1,
                expires_at=expires_at,
                updated_at=utcnow(),
            )
            .execution_options(synchronize_session=False)
        )
        return bool(getattr(changed, "rowcount", 0))

    def delete(self, name: str) -> bool:
        row = self._find(name)
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True

    def reseal_all(self) -> int:
        """Seal every secret again under the newest key (``outbound secrets rotate``)."""
        newest = self._keyring.newest
        rows = self._session.scalars(
            select(CredentialRow).where(
                CredentialRow.workspace_id == self._workspace_id,
                CredentialRow.key_version != newest,
            )
        ).all()
        for row in rows:
            aad = associated_data(row.workspace_id, row.id)
            secret = self._keyring.open(Sealed(row.key_version, row.nonce, row.ciphertext), aad)
            self._seal(row, secret)
        self._session.flush()
        return len(rows)

    def _seal(self, row: CredentialRow, secret: str) -> None:
        sealed = self._keyring.seal(secret, associated_data(self._workspace_id, row.id))
        row.key_version, row.nonce, row.ciphertext = (
            sealed.key_version,
            sealed.nonce,
            sealed.ciphertext,
        )

    def _find(self, name: str) -> CredentialRow | None:
        stmt = select(CredentialRow).where(
            CredentialRow.workspace_id == self._workspace_id, CredentialRow.name == name
        )
        return self._session.scalars(stmt).one_or_none()

    @staticmethod
    def _view(row: CredentialRow) -> Credential:
        return Credential(
            row.id,
            row.name,
            row.purpose,
            row.version,
            row.expires_at,
            dict(row.details or {}),
            row.updated_at,
        )
