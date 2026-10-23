"""Users, memberships, sign-in tokens, sessions and the audit log (Phase 6b).

These are platform tables, so there is no workspace scope and no row-level security: every
query here names exactly the rows it wants (a user, a token hash, one workspace's members).
Nothing else in the code reads these tables.
"""

from __future__ import annotations

from datetime import datetime
from types import TracebackType
from typing import Any, Self

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from outbound.db.errors import NotFound
from outbound.db.models import AuditRow, AuthTokenRow, MembershipRow, SessionRow, UserRow
from outbound.db.repositories.base import snapshot
from outbound.db.types import utcnow
from outbound.domain.entities import AuthToken, LoginSession, Membership, User
from outbound.domain.enums import AuthTokenPurpose, MembershipRole, PlatformRole, UserStatus


def normalise_email(email: str) -> str:
    return email.strip().lower()


class UserRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self, email: str, password_hash: str, *, name: str = "",
        platform_role: PlatformRole | None = None,
    ) -> User:  # fmt: skip
        row = UserRow(
            email=normalise_email(email),
            name=name.strip(),
            password_hash=password_hash,
            platform_role=platform_role,
        )
        self._session.add(row)
        self._session.flush()
        return snapshot(row, User)

    def get(self, user_id: str) -> User:
        return snapshot(self._row(user_id), User)

    def by_email(self, email: str) -> User | None:
        row = self._session.scalars(
            select(UserRow).where(UserRow.email == normalise_email(email))
        ).one_or_none()
        return snapshot(row, User) if row else None

    def password_hash(self, user_id: str) -> str:
        return self._row(user_id).password_hash

    def set_password(self, user_id: str, password_hash: str) -> None:
        self._row(user_id).password_hash = password_hash
        self._session.flush()

    def set_name(self, user_id: str, name: str) -> None:
        self._row(user_id).name = name.strip()
        self._session.flush()

    def logged_in(self, user_id: str) -> None:
        self._row(user_id).last_login_at = utcnow()
        self._session.flush()

    def accept_terms(self, user_id: str, version: str) -> None:
        row = self._row(user_id)
        row.terms_version, row.terms_accepted_at = version, utcnow()
        self._session.flush()

    def set_status(self, user_id: str, status: UserStatus) -> None:
        self._row(user_id).status = status
        self._session.flush()

    def set_platform_role(self, user_id: str, role: PlatformRole | None) -> None:
        self._row(user_id).platform_role = role
        self._session.flush()

    def all(self) -> list[User]:
        rows = self._session.scalars(select(UserRow).order_by(UserRow.email))
        return [snapshot(row, User) for row in rows]

    def _row(self, user_id: str) -> UserRow:
        row = self._session.get(UserRow, user_id)
        if row is None:
            raise NotFound(f"user {user_id}")
        return row


class MembershipRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, workspace_id: str, user_id: str, role: MembershipRole) -> Membership:
        row = MembershipRow(workspace_id=workspace_id, user_id=user_id, role=role)
        self._session.add(row)
        self._session.flush()
        return snapshot(row, Membership)

    def get(self, workspace_id: str, user_id: str) -> Membership | None:
        row = self._one(workspace_id, user_id)
        return snapshot(row, Membership) if row else None

    def for_user(self, user_id: str) -> list[Membership]:
        stmt = select(MembershipRow).where(MembershipRow.user_id == user_id)
        return [snapshot(row, Membership) for row in self._session.scalars(stmt)]

    def members(self, workspace_id: str) -> list[tuple[Membership, User]]:
        stmt = (
            select(MembershipRow, UserRow)
            .join(UserRow, UserRow.id == MembershipRow.user_id)
            .where(MembershipRow.workspace_id == workspace_id)
            .order_by(UserRow.email)
        )
        return [
            (snapshot(m, Membership), snapshot(u, User)) for m, u in self._session.execute(stmt)
        ]

    def count(self, workspace_id: str, role: MembershipRole | None = None) -> int:
        stmt = (
            select(func.count())
            .select_from(MembershipRow)
            .where(MembershipRow.workspace_id == workspace_id)
        )
        if role is not None:
            stmt = stmt.where(MembershipRow.role == role)
        return int(self._session.scalar(stmt) or 0)

    def set_role(self, workspace_id: str, user_id: str, role: MembershipRole) -> Membership:
        row = self._required(workspace_id, user_id)
        row.role = role
        self._session.flush()
        return snapshot(row, Membership)

    def remove(self, workspace_id: str, user_id: str) -> None:
        self._session.delete(self._required(workspace_id, user_id))
        self._session.flush()

    def _one(self, workspace_id: str, user_id: str) -> MembershipRow | None:
        stmt = select(MembershipRow).where(
            MembershipRow.workspace_id == workspace_id, MembershipRow.user_id == user_id
        )
        return self._session.scalars(stmt).one_or_none()

    def _required(self, workspace_id: str, user_id: str) -> MembershipRow:
        row = self._one(workspace_id, user_id)
        if row is None:
            raise NotFound(f"membership {workspace_id}/{user_id}")
        return row


class AuthTokenRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        purpose: AuthTokenPurpose,
        email: str,
        token_hash: str,
        expires_at: datetime,
        *,
        workspace_id: str | None = None,
        role: MembershipRole | None = None,
        created_by: str | None = None,
    ) -> AuthToken:
        row = AuthTokenRow(
            purpose=purpose,
            email=normalise_email(email),
            token_hash=token_hash,
            expires_at=expires_at,
            workspace_id=workspace_id,
            role=role,
            created_by=created_by,
        )
        self._session.add(row)
        self._session.flush()
        return snapshot(row, AuthToken)

    def by_hash(self, token_hash: str) -> AuthToken | None:
        row = self._session.scalars(
            select(AuthTokenRow).where(AuthTokenRow.token_hash == token_hash)
        ).one_or_none()
        return snapshot(row, AuthToken) if row else None

    def get(self, token_id: str) -> AuthToken:
        row = self._session.get(AuthTokenRow, token_id)
        if row is None:
            raise NotFound(f"token {token_id}")
        return snapshot(row, AuthToken)

    def use(self, token_id: str) -> None:
        self._set(token_id, used_at=utcnow())

    def revoke(self, token_id: str) -> None:
        self._set(token_id, revoked_at=utcnow())

    def replace_hash(self, token_id: str, token_hash: str, expires_at: datetime) -> None:
        self._set(token_id, token_hash=token_hash, expires_at=expires_at)

    def revoke_open(self, purpose: AuthTokenPurpose, email: str) -> None:
        """Retire every open link of this kind for this address (a new one replaces them)."""
        self._session.execute(
            update(AuthTokenRow)
            .where(
                AuthTokenRow.purpose == purpose,
                AuthTokenRow.email == normalise_email(email),
                AuthTokenRow.used_at.is_(None),
                AuthTokenRow.revoked_at.is_(None),
            )
            .values(revoked_at=utcnow())
        )

    def pending_invites(self, workspace_id: str, now: datetime) -> list[AuthToken]:
        stmt = (
            select(AuthTokenRow)
            .where(
                AuthTokenRow.purpose == AuthTokenPurpose.INVITE,
                AuthTokenRow.workspace_id == workspace_id,
                AuthTokenRow.used_at.is_(None),
                AuthTokenRow.revoked_at.is_(None),
                AuthTokenRow.expires_at > now,
            )
            .order_by(AuthTokenRow.created_at)
        )
        return [snapshot(row, AuthToken) for row in self._session.scalars(stmt)]

    def _set(self, token_id: str, **values: Any) -> None:
        row = self._session.get(AuthTokenRow, token_id)
        if row is None:
            raise NotFound(f"token {token_id}")
        for name, value in values.items():
            setattr(row, name, value)
        self._session.flush()


class SessionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self, user_id: str, token_hash: str, expires_at: datetime, *,
        ip: str | None = None, user_agent: str | None = None,
    ) -> LoginSession:  # fmt: skip
        row = SessionRow(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            ip=ip,
            user_agent=(user_agent or "")[:300] or None,
        )
        self._session.add(row)
        self._session.flush()
        return snapshot(row, LoginSession)

    def by_hash(self, token_hash: str) -> LoginSession | None:
        row = self._session.scalars(
            select(SessionRow).where(SessionRow.token_hash == token_hash)
        ).one_or_none()
        return snapshot(row, LoginSession) if row else None

    def seen(self, session_id: str, at: datetime) -> None:
        self._session.execute(
            update(SessionRow).where(SessionRow.id == session_id).values(last_seen_at=at)
        )

    def revoke(self, session_id: str) -> None:
        self._session.execute(
            update(SessionRow)
            .where(SessionRow.id == session_id, SessionRow.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )

    def revoke_for_user(self, user_id: str, *, keep: str | None = None) -> int:
        stmt = update(SessionRow).where(
            SessionRow.user_id == user_id, SessionRow.revoked_at.is_(None)
        )
        if keep is not None:
            stmt = stmt.where(SessionRow.id != keep)
        result = self._session.execute(stmt.values(revoked_at=utcnow()))
        return int(getattr(result, "rowcount", 0) or 0)

    def data(self, session_id: str) -> dict[str, Any]:
        row = self._session.get(SessionRow, session_id)
        return dict(row.data or {}) if row else {}

    def set_data(self, session_id: str, data: dict[str, Any]) -> None:
        row = self._session.get(SessionRow, session_id)
        if row is not None:
            row.data = data
            self._session.flush()


class AuditRepository:
    """Append-only: the roles can insert and read it, never change it."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self,
        action: str,
        *,
        actor_user_id: str | None,
        workspace_id: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        note: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        self._session.add(
            AuditRow(
                action=action,
                actor_user_id=actor_user_id,
                workspace_id=workspace_id,
                target_type=target_type,
                target_id=target_id,
                note=note,
                data=data or {},
                created_at=utcnow(),
            )
        )
        self._session.flush()

    def recent(self, *, workspace_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        stmt = select(AuditRow).order_by(AuditRow.created_at.desc(), AuditRow.id.desc())
        if workspace_id is not None:
            stmt = stmt.where(AuditRow.workspace_id == workspace_id)
        return [
            {
                "id": row.id,
                "at": row.created_at,
                "actor_user_id": row.actor_user_id,
                "workspace_id": row.workspace_id,
                "action": row.action,
                "target_type": row.target_type,
                "target_id": row.target_id,
                "note": row.note,
                "data": row.data,
            }
            for row in self._session.scalars(stmt.limit(limit))
        ]


class IdentityUnitOfWork:
    session: Session

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._factory = session_factory

    def __enter__(self) -> Self:
        self.session = self._factory()
        self.users = UserRepository(self.session)
        self.memberships = MembershipRepository(self.session)
        self.tokens = AuthTokenRepository(self.session)
        self.sessions = SessionRepository(self.session)
        self.audit = AuditRepository(self.session)
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


class IdentityUnitOfWorkFactory:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._factory = session_factory

    def __call__(self) -> IdentityUnitOfWork:
        return IdentityUnitOfWork(self._factory)
