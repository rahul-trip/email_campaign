"""A workspace's people: members, roles and invitations (Phase 6b)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from outbound.api.deps import Tenant, identity, require
from outbound.api.errors import ApiError
from outbound.api.schemas import (
    DecideJoinIn,
    InviteIn,
    JoinCodeOut,
    JoinRequestOut,
    MemberOut,
    PendingInviteOut,
    RoleIn,
    TeamOut,
)
from outbound.domain.enums import MembershipRole
from outbound.domain.permissions import Permission as P
from outbound.services.identity import IdentityError, IdentityService

router = APIRouter(prefix="/api/team", tags=["team"])
Ids = Annotated[IdentityService, Depends(identity)]


def _team(ids: IdentityService, workspace_id: str) -> TeamOut:
    team = ids.team(workspace_id)
    return TeamOut(
        members=[
            MemberOut(
                user_id=user.id,
                email=user.email,
                name=user.name,
                role=member.role.value,
                last_login_at=user.last_login_at,
            )
            for member, user in team.members
        ],
        invitations=[
            PendingInviteOut(
                id=i.id,
                email=i.email,
                role=(i.role or MembershipRole.MEMBER).value,
                expires_at=i.expires_at,
            )
            for i in team.invitations
        ],
        requests=[
            JoinRequestOut(
                id=request.id, user_id=user.id, email=user.email, name=user.name,
                requested_at=request.created_at,
            )
            for request, user in team.requests
        ],
        join_code=team.join_code,
    )  # fmt: skip


@router.get("", response_model=TeamOut)
def team(ctx: Annotated[Tenant, Depends(require(P.TEAM_READ))], ids: Ids) -> TeamOut:
    return _team(ids, ctx.workspace_id)


@router.post("/invitations", response_model=TeamOut, status_code=201)
def invite(
    body: InviteIn, ctx: Annotated[Tenant, Depends(require(P.TEAM_MANAGE))], ids: Ids
) -> TeamOut:
    try:
        ids.invite(ctx.workspace_id, body.email, MembershipRole(body.role), by=ctx.user.user.id)
    except IdentityError as error:
        raise ApiError(error.status, error.code, error.detail) from None
    return _team(ids, ctx.workspace_id)


@router.post("/invitations/{invitation_id}/resend", response_model=TeamOut)
def resend(
    invitation_id: str, ctx: Annotated[Tenant, Depends(require(P.TEAM_MANAGE))], ids: Ids
) -> TeamOut:
    try:
        ids.resend(ctx.workspace_id, invitation_id, by=ctx.user.user.id)
    except IdentityError as error:
        raise ApiError(error.status, error.code, error.detail) from None
    return _team(ids, ctx.workspace_id)


@router.delete("/invitations/{invitation_id}", response_model=TeamOut)
def revoke(
    invitation_id: str, ctx: Annotated[Tenant, Depends(require(P.TEAM_MANAGE))], ids: Ids
) -> TeamOut:
    ids.revoke_invite(ctx.workspace_id, invitation_id, by=ctx.user.user.id)
    return _team(ids, ctx.workspace_id)


@router.patch("/members/{user_id}", response_model=TeamOut)
def set_role(
    user_id: str, body: RoleIn, ctx: Annotated[Tenant, Depends(require(P.TEAM_MANAGE))], ids: Ids
) -> TeamOut:
    try:
        ids.set_role(ctx.workspace_id, user_id, MembershipRole(body.role), by=ctx.user.user.id)
    except IdentityError as error:
        raise ApiError(error.status, error.code, error.detail) from None
    return _team(ids, ctx.workspace_id)


@router.delete("/members/{user_id}", response_model=TeamOut)
def remove(
    user_id: str, ctx: Annotated[Tenant, Depends(require(P.TEAM_MANAGE))], ids: Ids
) -> TeamOut:
    try:
        ids.remove(ctx.workspace_id, user_id, by=ctx.user.user.id)
    except IdentityError as error:
        raise ApiError(error.status, error.code, error.detail) from None
    return _team(ids, ctx.workspace_id)


@router.post("/join-requests/{request_id}/approve", response_model=TeamOut)
def approve(
    request_id: str,
    body: DecideJoinIn,
    ctx: Annotated[Tenant, Depends(require(P.TEAM_MANAGE))],
    ids: Ids,
) -> TeamOut:
    try:
        ids.decide_join(
            ctx.workspace_id, request_id, approve=True, role=MembershipRole(body.role),
            by=ctx.user.user.id,
        )  # fmt: skip
    except IdentityError as error:
        raise ApiError(error.status, error.code, error.detail) from None
    return _team(ids, ctx.workspace_id)


@router.post("/join-requests/{request_id}/reject", response_model=TeamOut)
def reject(
    request_id: str, ctx: Annotated[Tenant, Depends(require(P.TEAM_MANAGE))], ids: Ids
) -> TeamOut:
    try:
        ids.decide_join(ctx.workspace_id, request_id, approve=False, by=ctx.user.user.id)
    except IdentityError as error:
        raise ApiError(error.status, error.code, error.detail) from None
    return _team(ids, ctx.workspace_id)


@router.post("/join-code", response_model=JoinCodeOut)
def new_join_code(ctx: Annotated[Tenant, Depends(require(P.TEAM_MANAGE))], ids: Ids) -> JoinCodeOut:
    """A new code; the old one stops working at once."""
    return JoinCodeOut(join_code=ids.new_join_code(ctx.workspace_id, by=ctx.user.user.id))
