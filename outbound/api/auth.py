"""Sign-in plumbing for the API (Phase 6b): the session cookie, the write header and the
per-address throttle.

The cookie holds a random token; the server keeps only its hash, in a session row it can
revoke (``outbound.services.identity``). It is HTTP-only and SameSite=Strict, and served over
https it is a ``__Host-`` cookie (Secure, the whole site, this host only). Every write must also
carry an ``X-Requested-With`` header, which a browser will not add to a cross-site request.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Request, Response

from outbound.api.errors import ApiError

COOKIE = "outbound_session"
SECURE_COOKIE = "__Host-outbound_session"  # needs https: browsers refuse it otherwise
CSRF_HEADER = "x-requested-with"


def _name(request: Request) -> str:
    return SECURE_COOKIE if request.app.state.cookie_secure else COOKIE


def session_token(request: Request) -> str | None:
    return request.cookies.get(_name(request))


def set_session(request: Request, response: Response, token: str, max_age: int) -> None:
    response.set_cookie(
        _name(request),
        token,
        max_age=max_age,
        httponly=True,
        samesite="strict",
        secure=request.app.state.cookie_secure,
        path="/",
    )


def clear_session(request: Request, response: Response) -> None:
    response.delete_cookie(
        _name(request), path="/", secure=request.app.state.cookie_secure, httponly=True
    )


class LoginThrottle:
    """At most ``attempts`` failed sign-ins per client address in ``window`` seconds."""

    def __init__(self, attempts: int = 5, window: float = 60.0) -> None:
        self._attempts = attempts
        self._window = window
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def blocked(self, client: str, now: float | None = None) -> bool:
        moment = time.monotonic() if now is None else now
        failures = self._failures[client]
        while failures and moment - failures[0] > self._window:
            failures.popleft()
        return len(failures) >= self._attempts

    def failed(self, client: str, now: float | None = None) -> None:
        self._failures[client].append(time.monotonic() if now is None else now)

    def succeeded(self, client: str) -> None:
        self._failures.pop(client, None)


def require_csrf_header(request: Request) -> None:
    if request.method not in {"GET", "HEAD", "OPTIONS"} and CSRF_HEADER not in request.headers:
        raise ApiError(403, "missing_header", "Send the X-Requested-With header with writes.")
