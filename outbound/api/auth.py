"""One local operator login: an Argon2 password hash from the environment, a signed cookie.

There are no user tables until Phase 6. The cookie is HTTP-only and SameSite=Strict, and every
write must also carry an ``X-Requested-With`` header, which a browser will not add to a
cross-site request. Failed logins are throttled per client.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from outbound.api.errors import ApiError

COOKIE = "outbound_session"
CSRF_HEADER = "x-requested-with"
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(stored_hash, password)
    except (VerificationError, InvalidHashError):
        return False


class Sessions:
    def __init__(self, secret: str, hours: int) -> None:
        if len(secret) < 16:
            raise ValueError("SESSION_SECRET must be at least 16 characters")
        self._signer = URLSafeTimedSerializer(secret, salt="outbound-session")
        self._max_age = hours * 3600

    @property
    def max_age(self) -> int:
        return self._max_age

    def issue(self) -> str:
        return self._signer.dumps({"user": "operator"})

    def valid(self, token: str | None) -> bool:
        if not token:
            return False
        try:
            data = self._signer.loads(token, max_age=self._max_age)
        except (BadSignature, SignatureExpired):
            return False
        return bool(data.get("user") == "operator")


class LoginThrottle:
    """At most ``attempts`` failed logins per client in ``window`` seconds."""

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


def require_operator(request: Request) -> None:
    sessions: Sessions = request.app.state.sessions
    if not sessions.valid(request.cookies.get(COOKIE)):
        raise ApiError(401, "unauthenticated", "Sign in to continue.")


def require_csrf_header(request: Request) -> None:
    if request.method not in {"GET", "HEAD", "OPTIONS"} and CSRF_HEADER not in request.headers:
        raise ApiError(403, "missing_header", "Send the X-Requested-With header with writes.")
