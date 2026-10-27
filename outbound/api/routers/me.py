"""What a signed-in person does before, or beside, any workspace: make one, ask to join one, and
read their notifications (Phase 6h). None of it names a workspace, so none of it is a tenant
route; each call acts only on the caller's own account."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from outbound.api.deps import current_user, identity
from outbound.api.errors import ApiError
from outbound.api.schemas import (
    CreateWorkspaceIn,
    JoinIn,
    MyJoinRequestOut,
    MyWorkspace,
    NotificationOut,
    NotificationsOut,
    ReadIn,
)
from outbound.services.identity import CurrentUser, IdentityError, IdentityService, MyJoinRequest

router = APIRouter(prefix="/api/me", tags=["me"])
Ids = Annotated[IdentityService, Depends(identity)]
User = Annotated[CurrentUser, Depends(current_user)]


def _request(found: MyJoinRequest) -> MyJoinRequestOut:
    return MyJoinRequestOut(
        id=found.request.id,
        workspace_name=found.workspace_name,
        status=found.request.status.value,
        created_at=found.request.created_at,
    )


@router.post("/workspaces", response_model=MyWorkspace, status_code=201)
def create_workspace(body: CreateWorkspaceIn, user: User, ids: Ids) -> MyWorkspace:
    """Make a workspace; the caller becomes its admin."""
    try:
        made = ids.create_my_workspace(user, body.name, website=body.website)
    except IdentityError as error:
        raise ApiError(error.status, error.code, error.detail) from None
    return MyWorkspace(
        id=made.id, slug=made.slug, name=made.name, status=made.status.value, role="admin"
    )


@router.get("/join-requests", response_model=list[MyJoinRequestOut])
def join_requests(user: User, ids: Ids) -> list[MyJoinRequestOut]:
    return [_request(found) for found in ids.my_join_requests(user)]


@router.post("/join-requests", response_model=MyJoinRequestOut, status_code=201)
def request_to_join(body: JoinIn, user: User, ids: Ids) -> MyJoinRequestOut:
    """Ask to join the workspace with this code; its admins are told and decide."""
    try:
        return _request(ids.request_to_join(user, body.code))
    except IdentityError as error:
        raise ApiError(error.status, error.code, error.detail) from None


@router.get("/notifications", response_model=NotificationsOut)
def notifications(user: User, ids: Ids) -> NotificationsOut:
    items, unread = ids.notifications(user)
    return NotificationsOut(
        items=[
            NotificationOut(
                id=n.id,
                kind=n.kind.value,
                workspace_id=n.workspace_id,
                data=n.data,
                read=n.read_at is not None,
                created_at=n.created_at,
            )
            for n in items
        ],
        unread=unread,
    )


@router.post("/notifications/read", status_code=204)
def mark_read(body: ReadIn, user: User, ids: Ids) -> None:
    ids.mark_notifications_read(user, body.id)
