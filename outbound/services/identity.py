"""People: signing in, sessions, invitations, password resets and teams (Phase 6b).

Accounts exist only by invitation (the alpha is invite-only). A platform admin creates a
customer's workspace and invites its first admin; workspace admins invite their own people.
Every link (invite or reset) is a random single-use token, stored only as a hash. A session is
a row the server can revoke; the browser holds only a random token in an HTTP-only cookie.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import timedelta

from outbound.db.errors import NotFound
from outbound.db.identity import IdentityUnitOfWork, IdentityUnitOfWorkFactory, normalise_email
from outbound.db.platform import PlatformUnitOfWorkFactory
from outbound.db.types import utcnow
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.entities import AuthToken, Membership, User, Workspace
from outbound.domain.enums import AuthTokenPurpose, MembershipRole, PlatformRole, UserStatus
from outbound.domain.passwords import (
    hash_password,
    hash_token,
    new_token,
    password_problem,
    verify_password,
)
from outbound.logging import get_logger
from outbound.providers.ports import OutgoingEmail, TransactionalEmail
from outbound.services.workspaces import create_workspace

log = get_logger(__name__)

INVITE_TTL = timedelta(days=7)
RESET_TTL = timedelta(minutes=30)
USER_IDLE, USER_ABSOLUTE = timedelta(hours=24), timedelta(days=14)
STAFF_IDLE, STAFF_ABSOLUTE = timedelta(hours=8), timedelta(days=3)
SEEN_EVERY = timedelta(minutes=5)  # how often last_seen_at is written


class IdentityError(Exception):
    """Refused, with a reason a person can act on. ``status`` and ``code`` are for the API."""

    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


@dataclass(frozen=True)
class CurrentUser:
    user: User
    session_id: str
    memberships: tuple[Membership, ...] = ()

    def role_in(self, workspace_id: str) -> MembershipRole | None:
        return next((m.role for m in self.memberships if m.workspace_id == workspace_id), None)


@dataclass(frozen=True)
class SignedIn:
    token: str  # goes in the cookie; never stored
    current: CurrentUser
    max_age: int  # seconds


@dataclass(frozen=True)
class InvitationView:
    email: str
    workspace_name: str
    role: MembershipRole
    has_account: bool


@dataclass(frozen=True)
class TeamView:
    members: list[tuple[Membership, User]]
    invitations: list[AuthToken]


@dataclass
class AccountThrottle:
    """At most ``attempts`` failed sign-ins per account in ``window`` seconds, whatever the IP."""

    attempts: int = 10
    window: float = 900.0
    _failures: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque))
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def blocked(self, key: str) -> bool:
        with self._lock:
            now, failures = time.monotonic(), self._failures[key]
            while failures and now - failures[0] > self.window:
                failures.popleft()
            return len(failures) >= self.attempts

    def failed(self, key: str) -> None:
        with self._lock:
            self._failures[key].append(time.monotonic())

    def succeeded(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


class IdentityService:
    def __init__(
        self,
        identity: IdentityUnitOfWorkFactory,
        platform: PlatformUnitOfWorkFactory,
        uow: UnitOfWorkFactory,
        email: TransactionalEmail,
        *,
        base_url: str,
        terms_version: str,
        throttle: AccountThrottle | None = None,
    ) -> None:
        self._identity = identity
        self._platform = platform
        self._uow = uow
        self._email = email
        self._base_url = base_url.rstrip("/")
        self._terms_version = terms_version
        self._throttle = throttle or AccountThrottle()

    # ------------------------------------------------------------------ sessions

    def login(
        self, email: str, password: str, *, ip: str | None = None, user_agent: str | None = None
    ) -> SignedIn:
        key = normalise_email(email)
        if self._throttle.blocked(key):
            raise IdentityError(429, "too_many_attempts", "Too many failed sign-ins. Wait a while.")
        with self._identity() as ids:
            user = ids.users.by_email(key)
            stored = ids.users.password_hash(user.id) if user else None
        # The same answer, and about the same time, whether or not the account exists.
        if user is None or stored is None or not verify_password(stored, password):
            if user is None:
                verify_password(_DUMMY_HASH, password)
            self._throttle.failed(key)
            log.warning("login_failed", user_id=user.id if user else None)
            raise IdentityError(401, "bad_credentials", "That email and password do not match.")
        if user.status is not UserStatus.ACTIVE:
            raise IdentityError(403, "account_disabled", "This account is disabled.")
        self._throttle.succeeded(key)
        signed = self._open_session(user, ip=ip, user_agent=user_agent)
        log.info("login_succeeded", user_id=user.id)
        return signed

    def authenticate(self, token: str | None) -> CurrentUser | None:
        """The signed-in person behind a cookie, or None if it is missing, revoked or expired."""
        if not token:
            return None
        now = utcnow()
        with self._identity() as ids:
            session = ids.sessions.by_hash(hash_token(token))
            if session is None or session.revoked_at is not None or session.expires_at <= now:
                return None
            user = ids.users.get(session.user_id)
            idle = STAFF_IDLE if user.platform_role else USER_IDLE
            if user.status is not UserStatus.ACTIVE or now - session.last_seen_at > idle:
                return None
            if now - session.last_seen_at > SEEN_EVERY:
                ids.sessions.seen(session.id, now)
                ids.commit()
            memberships = tuple(ids.memberships.for_user(user.id))
        return CurrentUser(user, session.id, memberships)

    def logout(self, token: str | None) -> None:
        if not token:
            return
        with self._identity() as ids:
            session = ids.sessions.by_hash(hash_token(token))
            if session is not None:
                ids.sessions.revoke(session.id)
                ids.commit()

    def logout_everywhere(self, current: CurrentUser) -> int:
        """Sign out every other browser; this one stays signed in."""
        with self._identity() as ids:
            count = ids.sessions.revoke_for_user(current.user.id, keep=current.session_id)
            ids.audit.record("sessions_revoked", actor_user_id=current.user.id, data={"n": count})
            ids.commit()
        return count

    def _open_session(
        self, user: User, *, ip: str | None = None, user_agent: str | None = None
    ) -> SignedIn:
        absolute = STAFF_ABSOLUTE if user.platform_role else USER_ABSOLUTE
        token, token_hash = new_token()
        with self._identity() as ids:
            session = ids.sessions.create(
                user.id, token_hash, utcnow() + absolute, ip=ip, user_agent=user_agent
            )
            ids.users.logged_in(user.id)
            memberships = tuple(ids.memberships.for_user(user.id))
            ids.commit()
        current = CurrentUser(user, session.id, memberships)
        return SignedIn(token, current, int(absolute.total_seconds()))

    # ------------------------------------------------------------------ passwords

    def change_password(self, current: CurrentUser, old: str, new: str) -> None:
        self._check_password(new, current.user.email)
        with self._identity() as ids:
            if not verify_password(ids.users.password_hash(current.user.id), old):
                raise IdentityError(400, "bad_credentials", "Your current password is not right.")
            ids.users.set_password(current.user.id, hash_password(new))
            ids.sessions.revoke_for_user(current.user.id, keep=current.session_id)
            ids.audit.record("password_changed", actor_user_id=current.user.id)
            ids.commit()
        self._send(current.user.email, "Your password was changed", _CHANGED)

    def forgot(self, email: str) -> None:
        """Email a reset link if the account exists. The caller always says the same thing."""
        with self._identity() as ids:
            user = ids.users.by_email(email)
            if user is None or user.status is not UserStatus.ACTIVE:
                return
            token, token_hash = new_token()
            ids.tokens.revoke_open(AuthTokenPurpose.RESET, user.email)
            ids.tokens.create(AuthTokenPurpose.RESET, user.email, token_hash, utcnow() + RESET_TTL)
            ids.commit()
        link = f"{self._base_url}/reset-password?token={token}"
        self._send(user.email, "Reset your Outbound password", _RESET.format(link=link))

    def reset(self, token: str, new: str) -> SignedIn:
        with self._identity() as ids:
            found = self._usable(ids, token, AuthTokenPurpose.RESET)
            user = ids.users.by_email(found.email)
            if user is None:
                raise IdentityError(400, "link_invalid", "This link is not valid any more.")
            self._check_password(new, user.email)
            ids.users.set_password(user.id, hash_password(new))
            ids.tokens.use(found.id)
            ids.sessions.revoke_for_user(user.id)
            ids.audit.record("password_reset", actor_user_id=user.id)
            ids.commit()
        return self._open_session(user)

    def _check_password(self, password: str, email: str) -> None:
        problem = password_problem(password, email=email)
        if problem:
            raise IdentityError(422, "weak_password", problem)

    def add_user(
        self,
        email: str,
        password: str,
        *,
        name: str = "",
        platform_role: PlatformRole | None = None,
        workspace_id: str | None = None,
        role: MembershipRole = MembershipRole.ADMIN,
        check_password: bool = True,
    ) -> User:
        """Create an account (or reuse one) without an invitation: the CLI's ``users create``,
        the first tenant's migration and tests. The person is added to ``workspace_id``."""
        if check_password:
            self._check_password(password, email)
        with self._identity() as ids:
            user = ids.users.by_email(email)
            if user is None:
                user = ids.users.create(email, hash_password(password), name=name)
                ids.users.accept_terms(user.id, self._terms_version)
            if platform_role is not None:
                ids.users.set_platform_role(user.id, platform_role)
            if workspace_id and ids.memberships.get(workspace_id, user.id) is None:
                ids.memberships.add(workspace_id, user.id, role)
            ids.audit.record(
                "user_added", actor_user_id=None, workspace_id=workspace_id,
                target_type="user", target_id=user.id,
                data={"platform_role": platform_role.value if platform_role else None},
            )  # fmt: skip
            ids.commit()
            return ids.users.get(user.id)

    # ------------------------------------------------------------------ invitations

    def invite(
        self, workspace_id: str, email: str, role: MembershipRole, *, by: str | None
    ) -> AuthToken:
        address = normalise_email(email)
        if "@" not in address or len(address) > 320:
            raise IdentityError(422, "bad_email", "Enter a valid email address.")
        with self._identity() as ids:
            existing = ids.users.by_email(address)
            if existing and ids.memberships.get(workspace_id, existing.id):
                raise IdentityError(409, "already_member", "That person is already in the team.")
            for open_invite in ids.tokens.pending_invites(workspace_id, utcnow()):
                if open_invite.email == address:
                    ids.tokens.revoke(open_invite.id)  # the new invitation replaces it
            token, token_hash = new_token()
            invitation = ids.tokens.create(
                AuthTokenPurpose.INVITE, address, token_hash, utcnow() + INVITE_TTL,
                workspace_id=workspace_id, role=role, created_by=by,
            )  # fmt: skip
            ids.audit.record(
                "member_invited", actor_user_id=by, workspace_id=workspace_id,
                target_type="email", data={"role": role.value},
            )  # fmt: skip
            ids.commit()
        self._send_invite(workspace_id, address, token)
        return invitation

    def resend(self, workspace_id: str, invitation_id: str, *, by: str | None) -> None:
        with self._identity() as ids:
            invitation = ids.tokens.get(invitation_id)
            if invitation.workspace_id != workspace_id or invitation.purpose is not (
                AuthTokenPurpose.INVITE
            ):
                raise NotFound(f"invitation {invitation_id}")
            token, token_hash = new_token()
            ids.tokens.replace_hash(invitation.id, token_hash, utcnow() + INVITE_TTL)
            ids.commit()
        self._send_invite(workspace_id, invitation.email, token)

    def revoke_invite(self, workspace_id: str, invitation_id: str, *, by: str | None) -> None:
        with self._identity() as ids:
            invitation = ids.tokens.get(invitation_id)
            if invitation.workspace_id != workspace_id:
                raise NotFound(f"invitation {invitation_id}")
            ids.tokens.revoke(invitation.id)
            ids.audit.record("invitation_revoked", actor_user_id=by, workspace_id=workspace_id)
            ids.commit()

    def invitation(self, token: str) -> InvitationView:
        with self._identity() as ids:
            found = self._usable(ids, token, AuthTokenPurpose.INVITE)
            has_account = ids.users.by_email(found.email) is not None
        workspace_id, role = _invited(found)
        return InvitationView(found.email, self._workspace(workspace_id).name, role, has_account)

    def accept(
        self,
        token: str,
        *,
        password: str | None = None,
        name: str = "",
        accept_terms: bool = False,
        current: CurrentUser | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> SignedIn | CurrentUser:
        """Join the workspace. A new person sets a password and accepts the Terms; someone with
        an account must already be signed in as the invited address."""
        with self._identity() as ids:
            found = self._usable(ids, token, AuthTokenPurpose.INVITE)
            workspace_id, role = _invited(found)
            user = ids.users.by_email(found.email)
            if user is not None:
                if current is None or current.user.id != user.id:
                    raise IdentityError(
                        403, "sign_in_first",
                        f"Sign in as {found.email} first, then open this link again.",
                    )  # fmt: skip
            else:
                if not accept_terms:
                    raise IdentityError(422, "terms_required", "Accept the Terms to continue.")
                if password is None:
                    raise IdentityError(422, "password_required", "Choose a password.")
                self._check_password(password, found.email)
                user = ids.users.create(found.email, hash_password(password), name=name)
                ids.users.accept_terms(user.id, self._terms_version)
            if ids.memberships.get(workspace_id, user.id) is None:
                ids.memberships.add(workspace_id, user.id, role)
            ids.tokens.use(found.id)
            ids.audit.record(
                "member_joined", actor_user_id=user.id, workspace_id=workspace_id,
                target_type="user", target_id=user.id, data={"role": role.value},
            )  # fmt: skip
            ids.commit()
        if current is not None:
            return self.authenticate_session(current)
        return self._open_session(user, ip=ip, user_agent=user_agent)

    def authenticate_session(self, current: CurrentUser) -> CurrentUser:
        with self._identity() as ids:
            memberships = tuple(ids.memberships.for_user(current.user.id))
        return CurrentUser(current.user, current.session_id, memberships)

    def _usable(self, ids: IdentityUnitOfWork, token: str, purpose: AuthTokenPurpose) -> AuthToken:
        found = ids.tokens.by_hash(hash_token(token))
        if (
            found is None
            or found.purpose is not purpose
            or found.used_at is not None
            or found.revoked_at is not None
            or found.expires_at <= utcnow()
        ):
            raise IdentityError(400, "link_invalid", "This link has expired or was already used.")
        return found

    def _send_invite(self, workspace_id: str, email: str, token: str) -> None:
        link = f"{self._base_url}/invite/{token}"
        name = self._workspace(workspace_id).name
        self._send(email, f"You're invited to {name} on Outbound", _INVITE.format(
            workspace=name, link=link, days=INVITE_TTL.days))  # fmt: skip

    # ------------------------------------------------------------------ teams

    def team(self, workspace_id: str) -> TeamView:
        with self._identity() as ids:
            return TeamView(
                ids.memberships.members(workspace_id),
                ids.tokens.pending_invites(workspace_id, utcnow()),
            )

    def set_role(
        self, workspace_id: str, user_id: str, role: MembershipRole, *, by: str | None
    ) -> Membership:
        with self._identity() as ids:
            current = ids.memberships.get(workspace_id, user_id)
            if current is None:
                raise NotFound(f"member {user_id}")
            if current.role is MembershipRole.ADMIN and role is not MembershipRole.ADMIN:
                self._keep_an_admin(ids, workspace_id)
            changed = ids.memberships.set_role(workspace_id, user_id, role)
            ids.audit.record(
                "role_changed", actor_user_id=by, workspace_id=workspace_id, target_type="user",
                target_id=user_id, data={"from": current.role.value, "to": role.value},
            )  # fmt: skip
            ids.commit()
        return changed

    def remove(self, workspace_id: str, user_id: str, *, by: str | None) -> None:
        with self._identity() as ids:
            current = ids.memberships.get(workspace_id, user_id)
            if current is None:
                raise NotFound(f"member {user_id}")
            if current.role is MembershipRole.ADMIN:
                self._keep_an_admin(ids, workspace_id)
            ids.memberships.remove(workspace_id, user_id)
            ids.audit.record(
                "member_removed", actor_user_id=by, workspace_id=workspace_id,
                target_type="user", target_id=user_id,
            )  # fmt: skip
            ids.commit()

    @staticmethod
    def _keep_an_admin(ids: IdentityUnitOfWork, workspace_id: str) -> None:
        if ids.memberships.count(workspace_id, MembershipRole.ADMIN) <= 1:
            raise IdentityError(
                409,
                "last_admin",
                "A workspace needs at least one admin. Make someone else admin first.",
            )

    # ------------------------------------------------------------------ directory

    def workspaces_of(self, current: CurrentUser) -> list[tuple[Workspace, MembershipRole | None]]:
        """The workspaces this person may open; for a superadmin, every active one."""
        roles = {m.workspace_id: m.role for m in current.memberships}
        with self._platform() as directory:
            if current.user.platform_role is PlatformRole.SUPERADMIN:
                found = directory.workspaces.all()
            else:
                found = [w for w in (directory.workspaces.get(i) for i in roles) if w]
        return [(w, roles.get(w.id)) for w in found]

    def _workspace(self, workspace_id: str) -> Workspace:
        with self._platform() as directory:
            found = directory.workspaces.get(workspace_id)
        if found is None:
            raise NotFound(f"workspace {workspace_id}")
        return found

    def create_customer(
        self, name: str, admin_email: str, *, by: str, website: str = ""
    ) -> tuple[Workspace, AuthToken]:
        """A platform admin creates a customer's workspace and invites its first admin."""
        if not name.strip():
            raise IdentityError(422, "name_required", "Give the company's name.")
        created = create_workspace(self._uow, self._platform, name, website=website)
        with self._identity() as ids:
            ids.audit.record(
                "customer_created", actor_user_id=by, workspace_id=created.id,
                target_type="workspace", target_id=created.id, data={"name": name},
            )  # fmt: skip
            ids.commit()
        return created, self.invite(created.id, admin_email, MembershipRole.ADMIN, by=by)

    def _send(self, to: str, subject: str, text: str) -> None:
        try:
            self._email.send(OutgoingEmail(to=to, subject=subject, text=text))
        except Exception:
            log.exception("email_failed", subject=subject)
            raise IdentityError(
                502, "email_failed", "The email could not be sent. Try again."
            ) from None


def _invited(token: AuthToken) -> tuple[str, MembershipRole]:
    if token.workspace_id is None or token.role is None:
        raise IdentityError(400, "link_invalid", "This link is not an invitation.")
    return token.workspace_id, token.role


# Verified against on unknown accounts, so a wrong email costs as much time as a wrong password.
_DUMMY_HASH = hash_password("not-a-real-password-just-for-timing")

_INVITE = """You have been invited to {workspace} on Outbound.

Open this link to join (it works for {days} days, once):
{link}

If you were not expecting this, you can ignore this email."""

_RESET = """Someone asked to reset the password for your Outbound account.

Open this link to choose a new one (it works for 30 minutes, once):
{link}

If it was not you, ignore this email: your password stays as it is."""

_CHANGED = """The password for your Outbound account was just changed, and other browsers were
signed out. If this was not you, reset your password now from the sign-in page."""
