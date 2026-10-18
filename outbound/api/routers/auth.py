from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from outbound.api.auth import COOKIE, LoginThrottle, Sessions, require_operator, verify_password
from outbound.api.errors import ApiError
from outbound.api.schemas import LoginIn, Me

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=Me)
def login(body: LoginIn, request: Request, response: Response) -> Me:
    throttle: LoginThrottle = request.app.state.throttle
    sessions: Sessions = request.app.state.sessions
    client = request.client.host if request.client else "unknown"
    if throttle.blocked(client):
        raise ApiError(429, "too_many_attempts", "Too many failed sign-ins. Wait a minute.")
    if not verify_password(request.app.state.password_hash, body.password):
        throttle.failed(client)
        raise ApiError(401, "bad_credentials", "That password is not right.")
    throttle.succeeded(client)
    response.set_cookie(
        COOKIE,
        sessions.issue(),
        max_age=sessions.max_age,
        httponly=True,
        samesite="strict",
        secure=request.app.state.cookie_secure,
    )
    return Me()


@router.post("/logout", status_code=204)
def logout(response: Response) -> None:
    response.delete_cookie(COOKIE)


@router.get("/me", response_model=Me, dependencies=[Depends(require_operator)])
def me() -> Me:
    return Me()
