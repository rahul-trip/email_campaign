"""Who may do what: fixed roles mapped to named permissions (Phase 6b).

Every API route declares the one permission it needs (``require`` in ``outbound.api.deps``),
and a test fails any tenant route that declares none. Roles are fixed in code; custom roles
would map onto the same permission names without touching a route.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from outbound.domain.enums import MembershipRole, PlatformRole


class Permission(StrEnum):
    # reading a workspace
    LEADS_READ = "leads.read"
    RUNS_READ = "runs.read"
    REVIEW_READ = "review.read"
    REPORTS_READ = "reports.read"
    SETTINGS_READ = "settings.read"
    TEAM_READ = "team.read"
    # day-to-day work (admins and members)
    LEADS_WRITE = "leads.write"
    RUNS_WRITE = "runs.write"
    REVIEW_WRITE = "review.write"
    CAMPAIGNS_WRITE = "campaigns.write"
    SUPPRESSIONS_WRITE = "suppressions.write"
    MAILBOXES_OWN = "mailboxes.own"
    DIRECTORY_REPORT = "directory.report"
    DIRECTORY_SKIP = "directory.skip"
    # running the workspace (admins)
    LEADS_DELETE = "leads.delete"
    PRIVACY_FORGET = "privacy.forget"
    COMPLIANCE_WRITE = "compliance.write"
    PROFILE_WRITE = "profile.write"
    SETTINGS_WRITE = "settings.write"
    MAILBOXES_MANAGE = "mailboxes.manage"
    TEAM_MANAGE = "team.manage"
    INTEGRATIONS_MANAGE = "integrations.manage"
    DATA_EXPORT = "data.export"
    WORKSPACE_DELETE = "workspace.delete"
    # the platform's own staff
    ADMIN_READ = "admin.read"
    ADMIN_WRITE = "admin.write"
    ADMIN_KEYS = "admin.keys"


P = Permission

READ: frozenset[Permission] = frozenset(
    {P.LEADS_READ, P.RUNS_READ, P.REVIEW_READ, P.REPORTS_READ, P.SETTINGS_READ, P.TEAM_READ}
)
WORK: frozenset[Permission] = READ | {
    P.LEADS_WRITE, P.RUNS_WRITE, P.REVIEW_WRITE, P.CAMPAIGNS_WRITE, P.SUPPRESSIONS_WRITE,
    P.MAILBOXES_OWN, P.DIRECTORY_REPORT, P.DIRECTORY_SKIP,
}  # fmt: skip
PLATFORM: frozenset[Permission] = frozenset({P.ADMIN_READ, P.ADMIN_WRITE, P.ADMIN_KEYS})
WORKSPACE_ALL: frozenset[Permission] = frozenset(set(Permission) - PLATFORM)

ROLE_PERMISSIONS: dict[MembershipRole, frozenset[Permission]] = {
    MembershipRole.ADMIN: WORKSPACE_ALL,
    MembershipRole.MEMBER: WORK,
}
PLATFORM_PERMISSIONS: dict[PlatformRole, frozenset[Permission]] = {
    PlatformRole.ADMIN: PLATFORM,
    PlatformRole.SUPERADMIN: PLATFORM,
}


@dataclass(frozen=True)
class Principal:
    """Who is asking, and as what, in the workspace a request acts in (if any)."""

    user_id: str
    role: MembershipRole | None = None  # None: not a member of this workspace
    platform_role: PlatformRole | None = None
    superadmin_view: bool = False  # a superadmin reading a workspace they do not belong to

    @property
    def permissions(self) -> frozenset[Permission]:
        found: set[Permission] = set()
        if self.role is not None:
            found |= ROLE_PERMISSIONS[self.role]
        if self.superadmin_view:
            found |= READ  # reads only: a superadmin view never writes
        if self.platform_role is not None:
            found |= PLATFORM_PERMISSIONS[self.platform_role]
        return frozenset(found)


def can(principal: Principal, permission: Permission, *, owner_id: str | None = None) -> bool:
    """Whether ``principal`` may do it. ``owner_id`` is the owner of the thing acted on: a
    member may manage a mailbox only if it is theirs (``MAILBOXES_OWN``)."""
    granted = principal.permissions
    if permission is P.MAILBOXES_OWN and owner_id is not None:
        return P.MAILBOXES_MANAGE in granted or (
            P.MAILBOXES_OWN in granted and owner_id == principal.user_id
        )
    return permission in granted
