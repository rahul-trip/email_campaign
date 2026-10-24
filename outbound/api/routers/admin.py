"""The platform's own console (Phase 6d): customers, plans, credits, people, settings, audit.

Platform admins and the alpha's superadmin only. Reads need ``admin.read``, changes ``admin.write``.
Everything here is counts, plans and settings: an admin sees how a customer uses the service,
never the content of its leads.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from outbound.api.deps import identity, require_platform
from outbound.api.errors import ApiError
from outbound.api.schemas import (
    AdminMailboxOut,
    AdminStepOut,
    AdminUserOut,
    AttentionOut,
    AuditOut,
    CustomerDetailOut,
    CustomerIn,
    CustomerOut,
    CustomerRowOut,
    DefaultPlanIn,
    ExtendAccessIn,
    GrantedOut,
    GrantIn,
    GrantOut,
    MemberOut,
    OverrideIn,
    OverrideOut,
    OverviewOut,
    PlanChangeIn,
    PlanDefinition,
    PlanSaveIn,
    PlansOut,
    PlatformRoleIn,
    PlatformSettingsIn,
    PlatformSettingsOut,
    StatusChangeIn,
)
from outbound.domain.entitlements import Plan
from outbound.domain.enums import PlatformRole, UsageStep, UserStatus, WorkspaceStatus
from outbound.domain.permissions import Permission as P
from outbound.domain.platform_settings import PlatformSettings
from outbound.services.admin import (
    AdminService,
    CustomerDetail,
    CustomerRow,
)
from outbound.services.identity import CurrentUser, IdentityError, IdentityService

router = APIRouter(prefix="/api/admin", tags=["admin"])
Reader = Annotated[CurrentUser, Depends(require_platform(P.ADMIN_READ))]
Writer = Annotated[CurrentUser, Depends(require_platform(P.ADMIN_WRITE))]


def admin(request: Request) -> AdminService:
    service: AdminService = request.app.state.admin
    return service


Admin = Annotated[AdminService, Depends(admin)]


# ------------------------------------------------------------------ mapping


def _row(row: CustomerRow) -> CustomerRowOut:
    quota = row.quota
    return CustomerRowOut(
        id=row.workspace.id,
        name=row.workspace.name,
        slug=row.workspace.slug,
        status=row.workspace.status.value,
        plan_code=row.plan.code,
        plan_name=row.plan.name,
        access=quota.access.value,
        access_until=quota.access_until,
        period_start=quota.period_start,
        period_end=quota.period_end,
        steps=[
            AdminStepOut(
                step=s.step.value,
                plan_limit=row.plan.limits.get(s.step),
                limit=s.limit,
                granted=s.granted,
                used=s.used,
                remaining=s.remaining,
            )
            for s in quota.steps.values()
        ],
        spend_micro_usd=row.spend_micro_usd,
        leads=row.leads,
        members=row.members,
        mailboxes=row.mailboxes,
        mailbox_problems=row.mailbox_problems,
        waiting=row.waiting,
        last_active=row.last_active,
        open_request=row.open_request,
        near_limit=row.near_limit,
        features=sorted(quota.entitlements.features),
    )


def _audit(entry: dict[str, Any]) -> AuditOut:
    return AuditOut(
        id=entry["id"],
        at=entry["at"],
        actor=entry.get("actor", ""),
        workspace=entry.get("workspace", ""),
        workspace_id=entry["workspace_id"],
        action=entry["action"],
        target_type=entry["target_type"],
        target_id=entry["target_id"],
        note=entry["note"],
        data=entry["data"] or {},
    )


def _detail(found: CustomerDetail) -> CustomerDetailOut:
    return CustomerDetailOut(
        row=_row(found.row),
        overrides=[
            OverrideOut(
                id=o.id, key=o.key, value=o.value, created_at=o.created_at,
                expires_at=o.expires_at, revoked_at=o.revoked_at, note=o.note,
            )
            for o in found.overrides
        ],
        grants=[
            GrantOut(
                id=g.id, step=g.step.value, amount=g.amount, created_at=g.created_at,
                expires_at=g.expires_at, revoked_at=g.revoked_at, note=g.note,
            )
            for g in found.grants
        ],
        members=[
            MemberOut(
                user_id=u.id, email=u.email, name=u.name, role=m.role.value,
                last_login_at=u.last_login_at,
            )
            for m, u in found.members
        ],
        mailboxes=[
            AdminMailboxOut(
                id=m.id, address=m.address, gateway=m.gateway.value, status=m.status.value,
                last_checked_at=m.last_checked_at,
                dns_ok=bool(m.dns_check.get("ok")) if m.dns_check else None,
            )
            for m in found.mailboxes
        ],
        requests=[_audit(a) for a in found.requests],
        activity=[_audit(a) for a in found.activity],
        plan_started_at=found.assignment.started_at if found.assignment else None,
        plan_note=found.assignment.note if found.assignment else "",
    )  # fmt: skip


def _plan(plan: Plan, customers: int) -> PlanDefinition:
    return PlanDefinition(
        code=plan.code,
        name=plan.name,
        limits={s.value: plan.limits.get(s) for s in UsageStep},
        seats=plan.seats,
        mailboxes=plan.mailboxes,
        active_campaigns=plan.active_campaigns,
        max_leads_per_run=plan.max_leads_per_run,
        max_prospect_budget_micro_usd=plan.max_prospect_budget_micro_usd,
        features=sorted(plan.features),
        access_days=plan.access_days,
        customers=customers,
    )


def _settings(settings: PlatformSettings, version: int) -> PlatformSettingsOut:
    return PlatformSettingsOut(
        kill_runs=settings.kill_runs,
        kill_drafts=settings.kill_drafts,
        superadmin_enabled=settings.superadmin_enabled,
        announcement=settings.announcement,
        version=version,
    )


# ------------------------------------------------------------------ overview and customers


@router.get("/overview", response_model=OverviewOut)
def overview(_: Reader, service: Admin) -> OverviewOut:
    found = service.overview()
    return OverviewOut(
        customers=found.customers,
        expiring=found.expiring,
        leads_added=found.leads_added,
        drafts_made=found.drafts_made,
        spend_micro_usd=found.spend_micro_usd,
        spend_by_provider=found.spend_by_provider,
        waiting=found.waiting,
        waiting_customers=found.waiting_customers,
        attention=[
            AttentionOut(
                kind=a.kind,
                workspace_id=a.workspace_id,
                workspace_name=a.workspace_name,
                detail=a.detail,
            )
            for a in found.attention
        ],
        activity=[_audit(a) for a in found.activity],
    )


@router.get("/customers", response_model=list[CustomerRowOut])
def customers(
    _: Reader,
    service: Admin,
    q: str = "",
    plan: str | None = None,
    access: str | None = None,
    near_limit: bool = False,
    waiting: bool = False,
    mailbox_problem: bool = False,
) -> list[CustomerRowOut]:
    rows = service.customers(
        search=q, plan=plan, access=access, near_limit=near_limit,
        waiting=waiting, mailbox_problem=mailbox_problem,
    )  # fmt: skip
    return [_row(r) for r in rows]


@router.post("/customers", response_model=CustomerOut, status_code=201)
def create_customer(
    body: CustomerIn, staff: Writer, ids: Annotated[IdentityService, Depends(identity)]
) -> CustomerOut:
    """Create a customer's workspace and invite its first admin."""
    try:
        workspace, invitation = ids.create_customer(
            body.name, body.admin_email, by=staff.user.id, website=body.website
        )
    except IdentityError as error:
        raise ApiError(error.status, error.code, error.detail) from None
    return CustomerOut(workspace_id=workspace.id, slug=workspace.slug, invited=invitation.email)


@router.get("/customers/{workspace_id}", response_model=CustomerDetailOut)
def customer(workspace_id: str, _: Reader, service: Admin) -> CustomerDetailOut:
    return _detail(service.customer(workspace_id))


@router.patch("/customers/{workspace_id}/plan", response_model=CustomerDetailOut)
def change_plan(
    workspace_id: str, body: PlanChangeIn, staff: Writer, service: Admin
) -> CustomerDetailOut:
    service.set_plan(workspace_id, body.plan, by=staff.user.id, note=body.note)
    return _detail(service.customer(workspace_id))


@router.post("/customers/{workspace_id}/access", response_model=CustomerDetailOut)
def extend_access(
    workspace_id: str, body: ExtendAccessIn, staff: Writer, service: Admin
) -> CustomerDetailOut:
    service.extend_access(
        workspace_id, by=staff.user.id, days=body.days, until=body.until, note=body.note
    )
    return _detail(service.customer(workspace_id))


@router.patch("/customers/{workspace_id}/status", response_model=CustomerDetailOut)
def change_status(
    workspace_id: str, body: StatusChangeIn, staff: Writer, service: Admin
) -> CustomerDetailOut:
    service.set_status(workspace_id, WorkspaceStatus(body.status), by=staff.user.id, note=body.note)
    return _detail(service.customer(workspace_id))


@router.put("/customers/{workspace_id}/overrides", response_model=CustomerDetailOut)
def set_override(
    workspace_id: str, body: OverrideIn, staff: Writer, service: Admin
) -> CustomerDetailOut:
    service.set_override(
        workspace_id, body.key, body.value, by=staff.user.id,
        expires_at=body.expires_at, note=body.note,
    )  # fmt: skip
    return _detail(service.customer(workspace_id))


@router.delete(
    "/customers/{workspace_id}/overrides/{override_id}", response_model=CustomerDetailOut
)
def revoke_override(
    workspace_id: str, override_id: str, staff: Writer, service: Admin
) -> CustomerDetailOut:
    service.revoke_override(workspace_id, override_id, by=staff.user.id)
    return _detail(service.customer(workspace_id))


@router.post("/customers/{workspace_id}/grants", response_model=GrantedOut, status_code=201)
def grant_credits(workspace_id: str, body: GrantIn, staff: Writer, service: Admin) -> GrantedOut:
    made, released = service.grant(
        workspace_id, UsageStep(body.step), body.amount, by=staff.user.id,
        expires_at=body.expires_at, note=body.note, resume_now=body.resume_now,
    )  # fmt: skip
    return GrantedOut(
        grant=GrantOut(
            id=made.id, step=made.step.value, amount=made.amount, created_at=made.created_at,
            expires_at=made.expires_at, revoked_at=made.revoked_at, note=made.note,
        ),
        resumed_leads=released.leads,
        resumed_rows=released.rows,
    )  # fmt: skip


@router.delete("/customers/{workspace_id}/grants/{grant_id}", response_model=CustomerDetailOut)
def revoke_grant(
    workspace_id: str, grant_id: str, staff: Writer, service: Admin
) -> CustomerDetailOut:
    service.revoke_grant(workspace_id, grant_id, by=staff.user.id)
    return _detail(service.customer(workspace_id))


@router.post("/customers/{workspace_id}/resume", response_model=CustomerDetailOut)
def resume(workspace_id: str, staff: Writer, service: Admin) -> CustomerDetailOut:
    service.resume(workspace_id, by=staff.user.id)
    return _detail(service.customer(workspace_id))


@router.post("/customers/{workspace_id}/dismiss-request", response_model=CustomerDetailOut)
def dismiss_request(workspace_id: str, staff: Writer, service: Admin) -> CustomerDetailOut:
    service.dismiss_request(workspace_id, by=staff.user.id)
    return _detail(service.customer(workspace_id))


# ------------------------------------------------------------------ users


@router.get("/users", response_model=list[AdminUserOut])
def users(_: Reader, service: Admin, q: str = "") -> list[AdminUserOut]:
    return [
        AdminUserOut(
            id=row.user.id,
            email=row.user.email,
            name=row.user.name,
            platform_role=row.user.platform_role.value if row.user.platform_role else None,
            status=row.user.status.value,
            last_login_at=row.user.last_login_at,
            workspaces=[f"{name} ({role})" for name, role in row.workspaces],
        )
        for row in service.users(q)
    ]


@router.post("/users/{user_id}/disable", status_code=204)
def disable_user(user_id: str, staff: Writer, service: Admin) -> None:
    if user_id == staff.user.id:
        raise ApiError(409, "not_yourself", "You cannot disable your own account.")
    service.set_user_status(user_id, UserStatus.DISABLED, by=staff.user.id)


@router.post("/users/{user_id}/enable", status_code=204)
def enable_user(user_id: str, staff: Writer, service: Admin) -> None:
    service.set_user_status(user_id, UserStatus.ACTIVE, by=staff.user.id)


@router.post("/users/{user_id}/sign-out")
def sign_out_user(user_id: str, staff: Writer, service: Admin) -> dict[str, int]:
    return {"signed_out": service.sign_out_everywhere(user_id, by=staff.user.id)}


@router.put("/users/{user_id}/platform-role", status_code=204)
def set_platform_role(user_id: str, body: PlatformRoleIn, staff: Writer, service: Admin) -> None:
    """Make someone platform staff, or take it away. The alpha's superadmin only."""
    if staff.user.platform_role is not PlatformRole.SUPERADMIN:
        raise ApiError(403, "forbidden", "Only a superadmin can change platform roles.")
    service.set_platform_role(
        user_id, PlatformRole(body.role) if body.role else None, by=staff.user.id
    )


# ------------------------------------------------------------------ plans and settings


@router.get("/plans", response_model=PlansOut)
def plans(_: Reader, service: Admin) -> PlansOut:
    settings, version = service.settings()
    counts = service.plan_customers()
    return PlansOut(
        plans=[_plan(p, counts.get(p.code, 0)) for p in settings.plans.values()],
        default_plan=settings.default_plan,
        version=version,
    )


@router.put("/plans/default", response_model=PlansOut)
def default_plan(body: DefaultPlanIn, staff: Writer, service: Admin) -> PlansOut:
    service.set_default_plan(body.plan, by=staff.user.id, version=body.version)
    return plans(staff, service)


@router.put("/plans/{code}", response_model=PlansOut)
def save_plan(code: str, body: PlanSaveIn, staff: Writer, service: Admin) -> PlansOut:
    plan = Plan(
        code=code,
        name=body.name.strip(),
        limits={UsageStep(step): value for step, value in body.limits.items()},
        seats=body.seats,
        mailboxes=body.mailboxes,
        active_campaigns=body.active_campaigns,
        max_leads_per_run=body.max_leads_per_run,
        max_prospect_budget_micro_usd=body.max_prospect_budget_micro_usd,
        features=frozenset(body.features),
        access_days=body.access_days,
    )
    service.save_plan(plan, by=staff.user.id, version=body.version)
    return plans(staff, service)


@router.get("/settings", response_model=PlatformSettingsOut)
def platform_settings(_: Reader, service: Admin) -> PlatformSettingsOut:
    return _settings(*service.settings())


@router.patch("/settings", response_model=PlatformSettingsOut)
def update_settings(body: PlatformSettingsIn, staff: Writer, service: Admin) -> PlatformSettingsOut:
    changes = body.model_dump(exclude={"version"}, exclude_none=True)
    return _settings(
        *service.update_settings(by=staff.user.id, version=body.version, changes=changes)
    )


# ------------------------------------------------------------------ audit


@router.get("/audit", response_model=list[AuditOut])
def audit(
    _: Reader,
    service: Admin,
    workspace_id: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[AuditOut]:
    rows = service.audit(
        workspace_id=workspace_id, actor_user_id=actor, action=action,
        since=since, until=until, limit=limit,
    )  # fmt: skip
    return [_audit(r) for r in rows]


@router.get("/audit.csv")
def audit_csv(
    _: Reader,
    service: Admin,
    workspace_id: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Response:
    text = service.audit_csv(
        workspace_id=workspace_id, actor_user_id=actor, action=action, since=since, until=until
    )
    return Response(
        text,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="audit.csv"'},
    )
