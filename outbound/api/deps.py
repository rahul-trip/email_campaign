"""What a request works with: who is asking, in which workspace, and the services for it.

- ``current_user``: the signed-in person behind the session cookie, or 401.
- ``tenant``: the workspace the request acts in (the ``X-Workspace-Id`` header; the person's
  only workspace when they have one and send none). A member gets their role there; a
  superadmin who is not a member gets a read-only view (Phase 6b, alpha only). Anyone else
  gets 403, so a forged header reaches nothing.
- ``require(permission)``: a route's one permission check. Every tenant route declares one.
- ``services``: that workspace's services, acting as the signed-in person. Vendor clients are
  built once per process; each request wraps them in its own workspace's meters.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends, Request

from outbound.api.auth import session_token
from outbound.api.errors import ApiError
from outbound.bootstrap import Container
from outbound.domain.actors import OPERATOR
from outbound.domain.enums import PlatformRole, WorkspaceStatus
from outbound.domain.permissions import Permission, Principal, can
from outbound.logging import bind, get_logger
from outbound.providers.ports import LlmClient, SearchProvider
from outbound.services.identity import CurrentUser, IdentityService
from outbound.services.intake import IntakeService
from outbound.services.leads import LeadService
from outbound.services.privacy import PrivacyService
from outbound.services.reports import ReportService
from outbound.services.review import ReviewService
from outbound.services.runs import RunService
from outbound.services.settings import SettingsService
from outbound.services.webhook import WebhookService
from outbound.stages.mailboxes import Mailboxes

log = get_logger(__name__)
WORKSPACE_HEADER = "x-workspace-id"


@dataclass(frozen=True)
class Services:
    container: Container
    workspace_id: str
    intake: IntakeService
    review: ReviewService
    leads: LeadService
    runs: RunService
    settings: SettingsService
    reports: ReportService
    webhook: WebhookService
    privacy: PrivacyService


def build_services(
    container: Container,
    workspace_id: str,
    *,
    search: SearchProvider | None = None,
    mailboxes: Mailboxes | None = None,
    writer: LlmClient | None = None,
    settings_service: SettingsService | None = None,
    actor: str = OPERATOR,
    read_only: bool = False,
) -> Services:
    uow = container.uow.reading_only() if read_only else container.uow
    intake = IntakeService(uow, workspace_id, search, actor=actor)
    return Services(
        container=container,
        workspace_id=workspace_id,
        intake=intake,
        review=ReviewService(uow, workspace_id, writer, actor=actor),
        leads=LeadService(uow, workspace_id, actor=actor),
        runs=RunService(uow, workspace_id),
        settings=settings_service or SettingsService(uow, workspace_id, actor=actor),
        reports=ReportService(uow, workspace_id),
        webhook=WebhookService(uow, workspace_id, intake),
        privacy=PrivacyService(uow, workspace_id, mailboxes, actor=actor),
    )


class ServicesSource(Protocol):
    def for_tenant(
        self, workspace_id: str, *, actor: str = OPERATOR, read_only: bool = False
    ) -> Services: ...


@dataclass(frozen=True)
class ServicesFactory:
    """Builds a request's services: shared vendor clients, this workspace's meters."""

    container: Container
    search: SearchProvider | None = None  # raw; metered per workspace
    writer: LlmClient | None = None  # raw; metered per workspace

    def for_tenant(
        self, workspace_id: str, *, actor: str = OPERATOR, read_only: bool = False
    ) -> Services:
        from outbound.pipeline import mailboxes_for, meter_search, meter_writer

        container = self.container
        return build_services(
            container,
            workspace_id,
            search=meter_search(container, workspace_id, self.search) if self.search else None,
            mailboxes=mailboxes_for(container, workspace_id),
            writer=meter_writer(container, workspace_id, self.writer) if self.writer else None,
            actor=actor,
            read_only=read_only,
        )


@dataclass(frozen=True)
class FixedServices:
    """Services built in advance for one workspace (tests and scripts)."""

    services: Services

    def for_tenant(
        self, workspace_id: str, *, actor: str = OPERATOR, read_only: bool = False
    ) -> Services:
        if workspace_id != self.services.workspace_id:
            raise ApiError(404, "not_found", "No such workspace.")
        return self.services


# ------------------------------------------------------------------ who and where


def identity(request: Request) -> IdentityService:
    service: IdentityService = request.app.state.identity
    return service


def current_user(
    request: Request, ids: Annotated[IdentityService, Depends(identity)]
) -> CurrentUser:
    user = ids.authenticate(session_token(request))
    if user is None:
        raise ApiError(401, "unauthenticated", "Sign in to continue.")
    bind(user_id=user.user.id)
    return user


@dataclass(frozen=True)
class Tenant:
    workspace_id: str
    principal: Principal
    user: CurrentUser

    @property
    def actor(self) -> str:
        return f"user:{self.user.user.id}"


def tenant(request: Request, user: Annotated[CurrentUser, Depends(current_user)]) -> Tenant:
    workspace_id = request.headers.get(WORKSPACE_HEADER, "").strip()
    if not workspace_id:
        if len(user.memberships) != 1:
            raise ApiError(400, "workspace_required", "Say which workspace (X-Workspace-Id).")
        workspace_id = user.memberships[0].workspace_id
    role = user.role_in(workspace_id)
    superadmin_view = (
        role is None
        and user.user.platform_role is PlatformRole.SUPERADMIN
        and request.app.state.superadmin_enabled
    )
    if role is None and not superadmin_view:
        log.warning("workspace_refused", workspace_id=workspace_id[:64])
        raise ApiError(403, "not_a_member", "You are not a member of that workspace.")
    status = _workspace_status(request, workspace_id)
    if status is None:
        raise ApiError(404, "not_found", "No such workspace.")
    if status in (WorkspaceStatus.SUSPENDED, WorkspaceStatus.DELETED) and not superadmin_view:
        raise ApiError(403, "workspace_closed", "This workspace is closed. Contact support.")
    principal = Principal(
        user_id=user.user.id,
        role=role,
        platform_role=user.user.platform_role,
        superadmin_view=superadmin_view,
    )
    bind(workspace_id=workspace_id)
    if superadmin_view:
        _audit_view(request, user, workspace_id)
    return Tenant(workspace_id, principal, user)


def _workspace_status(request: Request, workspace_id: str) -> WorkspaceStatus | None:
    container: Container = request.app.state.container
    with container.uow(workspace_id) as uow:
        found = uow.workspace()
    return found.status if found else None


def _audit_view(request: Request, user: CurrentUser, workspace_id: str) -> None:
    """One audit row per session and workspace a superadmin looks into."""
    seen: set[tuple[str, str]] = request.app.state.superadmin_views
    key = (user.session_id, workspace_id)
    if key in seen:
        return
    container: Container = request.app.state.container
    with container.identity() as ids:
        ids.audit.record(
            "superadmin_viewed_workspace", actor_user_id=user.user.id, workspace_id=workspace_id
        )
        ids.commit()
    seen.add(key)
    log.warning("superadmin_view", workspace_id=workspace_id)


Check = Callable[..., object]


def require(permission: Permission) -> Check:
    """A route's permission. As a dependency it returns the request's tenant, checked."""

    def check(context: Annotated[Tenant, Depends(tenant)]) -> Tenant:
        if not can(context.principal, permission):
            refusal = (
                "A superadmin view is read-only."
                if context.principal.superadmin_view
                else "Your role does not allow this. Ask a workspace admin."
            )
            raise ApiError(403, "forbidden", refusal)
        return context

    check.permission = permission  # type: ignore[attr-defined]  # read by the route-walk test
    return check


def require_platform(permission: Permission) -> Check:
    """A platform-console route: the platform's own staff only, whatever their workspaces."""

    def check(user: Annotated[CurrentUser, Depends(current_user)]) -> CurrentUser:
        if not can(Principal(user.user.id, platform_role=user.user.platform_role), permission):
            raise ApiError(403, "forbidden", "This is for the platform's own staff.")
        return user

    check.permission = permission  # type: ignore[attr-defined]
    return check


def services(request: Request, context: Annotated[Tenant, Depends(tenant)]) -> Services:
    source: ServicesSource = request.app.state.services_source
    return source.for_tenant(
        context.workspace_id,
        actor=context.actor,
        read_only=context.principal.superadmin_view,
    )


def deployment_workspace(request: Request) -> str:
    """The intake webhook's workspace until Phase 6c gives every workspace its own URL."""
    workspace_id: str = request.app.state.workspace_id
    return workspace_id
