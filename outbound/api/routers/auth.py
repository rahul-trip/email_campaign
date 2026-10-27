"""Signing in and out, passwords, and accepting an invitation (Phase 6b)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool

from outbound.api.auth import LoginThrottle, clear_session, session_token, set_session
from outbound.api.deps import current_user, identity
from outbound.api.errors import ApiError
from outbound.api.schemas import (
    AcceptIn,
    ChangePasswordIn,
    ForgotIn,
    InvitationOut,
    LoginIn,
    Me,
    MyWorkspace,
    RemovalConfirmIn,
    RemovalIn,
    ResetIn,
    UserOut,
)
from outbound.logging import bind
from outbound.services.identity import CurrentUser, IdentityError, IdentityService, SignedIn

router = APIRouter(prefix="/api/auth", tags=["auth"])
Ids = Annotated[IdentityService, Depends(identity)]
User = Annotated[CurrentUser, Depends(current_user)]


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _me(ids: IdentityService, user: CurrentUser) -> Me:
    return Me(
        user=UserOut(
            id=user.user.id,
            email=user.user.email,
            name=user.user.name,
            platform_role=user.user.platform_role.value if user.user.platform_role else None,
        ),
        workspaces=[
            MyWorkspace(
                id=w.id,
                slug=w.slug,
                name=w.name,
                status=w.status.value,
                role=role.value if role else None,
            )
            for w, role in ids.workspaces_of(user)
        ],
    )


def _signed_in(request: Request, response: Response, ids: IdentityService, signed: SignedIn) -> Me:
    set_session(request, response, signed.token, signed.max_age)
    return _me(ids, signed.current)


def _refuse(error: IdentityError) -> ApiError:
    return ApiError(error.status, error.code, error.detail)


@router.post("/login", response_model=Me)
def login(body: LoginIn, request: Request, response: Response, ids: Ids) -> Me:
    throttle: LoginThrottle = request.app.state.throttle
    client = _client(request)
    bind(client_ip=client)
    if throttle.blocked(client):
        raise ApiError(429, "too_many_attempts", "Too many failed sign-ins. Wait a minute.")
    try:
        signed = ids.login(
            body.email, body.password, ip=client, user_agent=request.headers.get("user-agent")
        )
    except IdentityError as error:
        if error.code == "bad_credentials":
            throttle.failed(client)
        raise _refuse(error) from None
    throttle.succeeded(client)
    return _signed_in(request, response, ids, signed)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, ids: Ids) -> None:
    ids.logout(session_token(request))
    clear_session(request, response)


@router.post("/logout-others")
def logout_others(user: User, ids: Ids) -> dict[str, int]:
    return {"signed_out": ids.logout_everywhere(user)}


@router.get("/me", response_model=Me)
def me(user: User, ids: Ids) -> Me:
    return _me(ids, user)


@router.post("/password/forgot", status_code=202)
async def forgot(body: ForgotIn, ids: Ids) -> dict[str, str]:
    # Sending can take a moment; the answer is the same whether or not the account exists.
    await run_in_threadpool(ids.forgot, body.email)
    return {"detail": "If that address has an account, a reset link is on its way."}


@router.post("/password/reset", response_model=Me)
def reset(body: ResetIn, request: Request, response: Response, ids: Ids) -> Me:
    try:
        return _signed_in(request, response, ids, ids.reset(body.token, body.password))
    except IdentityError as error:
        raise _refuse(error) from None


@router.post("/password/change", status_code=204)
def change_password(body: ChangePasswordIn, user: User, ids: Ids) -> None:
    try:
        ids.change_password(user, body.current_password, body.new_password)
    except IdentityError as error:
        raise _refuse(error) from None


@router.get("/invitations/{token}", response_model=InvitationOut)
def invitation(token: str, ids: Ids) -> InvitationOut:
    try:
        found = ids.invitation(token)
    except IdentityError as error:
        raise _refuse(error) from None
    return InvitationOut(
        email=found.email,
        workspace_name=found.workspace_name,
        role=found.role.value if found.role else None,
        has_account=found.has_account,
    )


@router.post("/invitations/{token}/accept", response_model=Me)
def accept(token: str, body: AcceptIn, request: Request, response: Response, ids: Ids) -> Me:
    current = ids.authenticate(session_token(request))
    try:
        result = ids.accept(
            token,
            password=body.password,
            name=body.name,
            accept_terms=body.accept_terms,
            current=current,
            ip=_client(request),
            user_agent=request.headers.get("user-agent"),
        )
    except IdentityError as error:
        raise _refuse(error) from None
    if isinstance(result, SignedIn):
        return _signed_in(request, response, ids, result)
    return _me(ids, result)


@router.post("/remove-my-data", status_code=202)
async def request_removal(body: RemovalIn, ids: Ids) -> dict[str, str]:
    """Public. Sends a confirmation link to the address; never says whether we held it."""
    await run_in_threadpool(ids.request_data_removal, body.email)
    return {"detail": "If that address is a valid one, a confirmation link is on its way."}


@router.post("/remove-my-data/confirm", status_code=200)
def confirm_removal(body: RemovalConfirmIn, ids: Ids) -> dict[str, str]:
    try:
        ids.confirm_data_removal(body.token)
    except IdentityError as error:
        raise _refuse(error) from None
    return {"detail": "Done. Your details were removed and will not be added again."}
