"""Plan, use and credits (Phase 6d), and letting waiting work continue."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from outbound.api.deps import Services, Tenant, require, services
from outbound.api.schemas import (
    GrantOut,
    RequestCreditsIn,
    ResumedOut,
    StepUsageOut,
    UsageOut,
)
from outbound.domain.enums import UsageStep
from outbound.domain.permissions import Permission as P

router = APIRouter(prefix="/api", tags=["usage"])
Svc = Annotated[Services, Depends(services)]
WORK = [Depends(require(P.LEADS_WRITE))]


@router.get("/usage", response_model=UsageOut, dependencies=[Depends(require(P.LEADS_READ))])
def usage(svc: Svc) -> UsageOut:
    report = svc.usage.report()
    quota = report.quota
    return UsageOut(
        plan_code=quota.plan.code,
        plan_name=quota.plan.name,
        period_start=quota.period_start,
        period_end=quota.period_end,
        access=quota.access.value,
        access_until=quota.access_until,
        engine=quota.engine,
        steps=[
            StepUsageOut(
                step=s.step.value,
                limit=s.limit,
                granted=s.granted,
                used=s.used,
                remaining=s.remaining,
            )
            for s in quota.steps.values()
        ],
        grants=[
            GrantOut(
                id=g.id, step=g.step.value, amount=g.amount, created_at=g.created_at,
                expires_at=g.expires_at, revoked_at=g.revoked_at, note=g.note,
            )
            for g in report.grants
        ],
        waiting_leads=report.waiting_by_step,
        waiting_rows=report.waiting_rows,
        seats=quota.entitlements.seats,
        mailboxes=quota.entitlements.mailboxes,
        active_campaigns=quota.entitlements.active_campaigns,
        features=sorted(quota.entitlements.features),
        announcement=report.announcement,
    )  # fmt: skip


@router.post("/usage/request-credits", status_code=202)
def request_credits(
    # A read permission: asking for more must work when access has ended and writes are refused.
    body: RequestCreditsIn,
    ctx: Annotated[Tenant, Depends(require(P.LEADS_READ))],
    svc: Svc,
) -> dict[str, str]:
    step = UsageStep(body.step) if body.step else None
    svc.usage.request_credits(ctx.user.user.id, step, body.note)
    return {"detail": "Your request was sent to the team."}


@router.post("/companies/resume", response_model=ResumedOut, dependencies=WORK)
def resume_all(ctx: Annotated[Tenant, Depends(require(P.LEADS_WRITE))], svc: Svc) -> ResumedOut:
    """Let every waiting lead and row continue, as far as the credits go."""
    released = svc.resume.release_all(actor=ctx.actor)
    return ResumedOut(leads=released.leads, rows=released.rows)


@router.post("/companies/{company_id}/resume", response_model=ResumedOut)
def resume_one(
    company_id: str, ctx: Annotated[Tenant, Depends(require(P.LEADS_WRITE))], svc: Svc
) -> ResumedOut:
    svc.resume.resume_lead(company_id, actor=ctx.actor)
    return ResumedOut(leads=1, rows=0)


@router.post("/targets/resume", response_model=ResumedOut)
def resume_rows(ctx: Annotated[Tenant, Depends(require(P.LEADS_WRITE))], svc: Svc) -> ResumedOut:
    """Add the manual rows that waited for credits."""
    return ResumedOut(leads=0, rows=svc.intake.release_waiting(actor=ctx.actor))
