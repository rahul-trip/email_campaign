"""Mailboxes, connected and managed from Settings only (Phase 6c).

Members connect and look after their own mailboxes (``mailboxes.own``); admins manage every
mailbox in the workspace (``mailboxes.manage``), including which one is the default.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from outbound.api.deps import Services, ServicesSource, Tenant, current_user, require, services
from outbound.api.errors import ApiError
from outbound.api.schemas import (
    ImapIn,
    MailboxCheckOut,
    MailboxOptionsOut,
    MailboxOut,
    OAuthFinishIn,
    OAuthFinishOut,
    OAuthStartIn,
    OAuthStartOut,
    SenderIn,
)
from outbound.db.repositories.workspaces import MailboxView
from outbound.domain.enums import MailboxGateway
from outbound.domain.permissions import Permission as P
from outbound.domain.permissions import Principal, can
from outbound.services.identity import CurrentUser
from outbound.services.mailboxes import ImapSettings, MailboxError, pending_workspace

router = APIRouter(prefix="/api/mailboxes", tags=["mailboxes"])
Svc = Annotated[Services, Depends(services)]


def _out(view: MailboxView) -> MailboxOut:
    return MailboxOut.model_validate(view)


def _refuse(error: MailboxError) -> ApiError:
    return ApiError(error.status, error.code, error.detail)


def _own(ctx: Tenant, svc: Services, mailbox_id: str) -> MailboxView:
    """The mailbox, if this person may act on it: theirs, or any for an admin."""
    view = svc.mailboxes.get(mailbox_id)
    allowed = (
        can(ctx.principal, P.MAILBOXES_OWN, owner_id=view.owner_user_id)
        if view.owner_user_id
        else can(ctx.principal, P.MAILBOXES_MANAGE)  # nobody's own: the workspace's, for admins
    )
    if not allowed:
        raise ApiError(
            403, "forbidden", "Only its owner or a workspace admin can change this mailbox."
        )
    return view


@router.get("", response_model=list[MailboxOut], dependencies=[Depends(require(P.SETTINGS_READ))])
def all_mailboxes(svc: Svc) -> list[MailboxOut]:
    return [_out(m) for m in svc.mailboxes.all()]


@router.get(
    "/options", response_model=MailboxOptionsOut, dependencies=[Depends(require(P.SETTINGS_READ))]
)
def options(svc: Svc) -> MailboxOptionsOut:
    return MailboxOptionsOut(gateways=[g.value for g in svc.mailboxes.gateways()])


@router.post("/oauth/start", response_model=OAuthStartOut)
def oauth_start(
    body: OAuthStartIn, ctx: Annotated[Tenant, Depends(require(P.MAILBOXES_OWN))], svc: Svc
) -> OAuthStartOut:
    try:
        url = svc.mailboxes.start_oauth(
            MailboxGateway(body.gateway), session_id=ctx.user.session_id,
            user_id=ctx.user.user.id, login_hint=body.login_hint,
        )  # fmt: skip
    except MailboxError as error:
        raise _refuse(error) from None
    return OAuthStartOut(url=url)


@router.post("/oauth/finish", response_model=OAuthFinishOut)
def oauth_finish(
    body: OAuthFinishIn, request: Request, user: Annotated[CurrentUser, Depends(current_user)]
) -> OAuthFinishOut:
    """Back from Microsoft or Google. The page there does not know the workspace, so it comes
    from the sign-in this session started; the person must still be allowed to act there."""
    workspace_id = pending_workspace(request.app.state.container.identity, user.session_id)
    if workspace_id is None:
        raise ApiError(
            400, "oauth_state", "No mailbox sign-in is waiting. Start again from Settings."
        )
    principal = Principal(
        user.user.id, role=user.role_in(workspace_id), platform_role=user.user.platform_role
    )
    if not can(principal, P.MAILBOXES_OWN):
        raise ApiError(403, "forbidden", "You cannot connect mailboxes in that workspace.")
    source: ServicesSource = request.app.state.services_source
    svc = source.for_tenant(workspace_id, actor=f"user:{user.user.id}")
    try:
        view = svc.mailboxes.finish_oauth(
            session_id=user.session_id, code=body.code, state=body.state
        )
    except MailboxError as error:
        raise _refuse(error) from None
    with svc.container.uow(workspace_id) as uow:
        workspace = uow.workspace()
    return OAuthFinishOut(slug=workspace.slug if workspace else "", mailbox=_out(view))


@router.post("/imap", response_model=MailboxOut, status_code=201)
def connect_imap(
    body: ImapIn, ctx: Annotated[Tenant, Depends(require(P.MAILBOXES_OWN))], svc: Svc
) -> MailboxOut:
    settings = ImapSettings(
        address=body.address, host=body.host, port=body.port, username=body.username,
        password=body.password, drafts_folder=body.drafts_folder, sent_folder=body.sent_folder,
    )  # fmt: skip
    try:
        return _out(svc.mailboxes.connect_imap(settings, owner_user_id=ctx.user.user.id))
    except MailboxError as error:
        raise _refuse(error) from None


@router.post("/{mailbox_id}/test", response_model=MailboxCheckOut)
def test_mailbox(
    mailbox_id: str, ctx: Annotated[Tenant, Depends(require(P.MAILBOXES_OWN))], svc: Svc
) -> MailboxCheckOut:
    _own(ctx, svc, mailbox_id)
    return MailboxCheckOut.model_validate(svc.mailboxes.test(mailbox_id))


@router.post("/{mailbox_id}/pause", response_model=MailboxOut)
def pause(
    mailbox_id: str, ctx: Annotated[Tenant, Depends(require(P.MAILBOXES_OWN))], svc: Svc
) -> MailboxOut:
    _own(ctx, svc, mailbox_id)
    return _out(svc.mailboxes.pause(mailbox_id))


@router.post("/{mailbox_id}/resume", response_model=MailboxOut)
def resume(
    mailbox_id: str, ctx: Annotated[Tenant, Depends(require(P.MAILBOXES_OWN))], svc: Svc
) -> MailboxOut:
    _own(ctx, svc, mailbox_id)
    return _out(svc.mailboxes.resume(mailbox_id))


@router.post(
    "/{mailbox_id}/default",
    response_model=MailboxOut,
    dependencies=[Depends(require(P.MAILBOXES_MANAGE))],
)
def make_default(mailbox_id: str, svc: Svc) -> MailboxOut:
    return _out(svc.mailboxes.make_default(mailbox_id))


@router.put("/{mailbox_id}/sender", response_model=MailboxOut)
def set_sender(
    mailbox_id: str,
    body: SenderIn,
    ctx: Annotated[Tenant, Depends(require(P.MAILBOXES_OWN))],
    svc: Svc,
) -> MailboxOut:
    _own(ctx, svc, mailbox_id)
    return _out(svc.mailboxes.set_sender(mailbox_id, body.model_dump()))


@router.delete("/{mailbox_id}", status_code=204)
def disconnect(
    mailbox_id: str, ctx: Annotated[Tenant, Depends(require(P.MAILBOXES_OWN))], svc: Svc
) -> None:
    _own(ctx, svc, mailbox_id)
    svc.mailboxes.disconnect(mailbox_id)
