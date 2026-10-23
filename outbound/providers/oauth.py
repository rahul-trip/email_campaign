"""OAuth 2.0 for the mailboxes customers connect: authorization code with PKCE (RFC 7636).

The browser is sent to the provider with a random ``state`` and a code challenge; the provider
sends it back with a code, which is exchanged here, once, for an access token and a refresh
token. Refreshing later uses only the refresh token. Microsoft issues a new refresh token on
every refresh (the old one keeps working for a while); Google usually does not, so the old one
is kept. A refused refresh (``invalid_grant``: revoked, expired, password changed) means the
person must connect again.

Docs:
- Microsoft: https://learn.microsoft.com/entra/identity-platform/v2-oauth2-auth-code-flow
- Google: https://developers.google.com/identity/protocols/oauth2/web-server
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict

from outbound.providers.errors import ProviderError, ReconnectNeeded
from outbound.providers.http import HttpClient

MICROSOFT_SCOPES = ("offline_access", "User.Read", "Mail.ReadWrite")
GOOGLE_SCOPES = (
    "openid",
    "email",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.readonly",
)


@dataclass(frozen=True)
class OAuthApp:
    provider: str  # "graph" or "gmail", the mailbox gateway it connects
    client_id: str
    client_secret: str
    authorize_url: str
    token_url: str
    scopes: tuple[str, ...]
    extra: dict[str, str] = field(default_factory=dict)  # added to the authorization request

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)


def microsoft(client_id: str, client_secret: str) -> OAuthApp:
    """Our multi-tenant Entra app: any Microsoft 365 or Outlook account can sign in."""
    base = "https://login.microsoftonline.com/common/oauth2/v2.0"
    return OAuthApp(
        "graph", client_id, client_secret, f"{base}/authorize", f"{base}/token",
        MICROSOFT_SCOPES, {"response_mode": "query"},
    )  # fmt: skip


def google(client_id: str, client_secret: str) -> OAuthApp:
    """``access_type=offline`` and ``prompt=consent`` so Google always returns a refresh token."""
    offline = {"access_type": "offline", "prompt": "consent", "include_granted_scopes": "true"}
    return OAuthApp(
        "gmail", client_id, client_secret,
        "https://accounts.google.com/o/oauth2/v2/auth", "https://oauth2.googleapis.com/token",
        GOOGLE_SCOPES, offline,
    )  # fmt: skip


class TokenSet(BaseModel):
    """What a mailbox connection stores, sealed, in its credential."""

    model_config = ConfigDict(frozen=True)

    access_token: str
    refresh_token: str
    expires_at: datetime
    scope: str = ""

    def expiring(self, now: datetime, margin: timedelta = timedelta(minutes=5)) -> bool:
        return self.expires_at - margin <= now


def pkce_pair() -> tuple[str, str]:
    """A code verifier (kept server-side) and its S256 challenge (sent to the provider)."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def authorization_url(
    app: OAuthApp, *, redirect_uri: str, state: str, challenge: str, login_hint: str | None = None
) -> str:
    params = {
        "client_id": app.client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": " ".join(app.scopes),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        **app.extra,
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{app.authorize_url}?{urlencode(params)}"


class OAuthClient:
    """Talks to one provider's token endpoint."""

    def __init__(
        self,
        app: OAuthApp,
        *,
        client: httpx.Client | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._app = app
        self._now = now
        self._http = HttpClient(f"{app.provider}_oauth", app.token_url, client=client)

    def exchange(self, code: str, verifier: str, redirect_uri: str) -> TokenSet:
        """The code from the browser, once, for tokens."""
        answer = self._token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": redirect_uri,
            }
        )
        if not answer.get("refresh_token"):
            raise ProviderError(self._app.provider, "no refresh token was granted; connect again")
        return self._tokens(answer, previous_refresh=None)

    def refresh(self, refresh_token: str) -> TokenSet:
        try:
            answer = self._token({"grant_type": "refresh_token", "refresh_token": refresh_token})
        except ProviderError as error:
            if error.status_code in (400, 401):  # invalid_grant: revoked, expired, consent gone
                raise ReconnectNeeded(self._app.provider, "access was revoked or expired") from None
            raise
        return self._tokens(answer, previous_refresh=refresh_token)

    def _token(self, form: dict[str, str]) -> dict[str, object]:
        body = {"client_id": self._app.client_id, "client_secret": self._app.client_secret, **form}
        if form["grant_type"] == "refresh_token" and self._app.provider == "graph":
            body["scope"] = " ".join(self._app.scopes)
        answer = self._http.request("POST", "", data=body)
        if not isinstance(answer, dict) or not answer.get("access_token"):
            raise ProviderError(self._app.provider, "the token endpoint gave no access token")
        return answer

    def _tokens(self, answer: dict[str, object], *, previous_refresh: str | None) -> TokenSet:
        lifetime = int(str(answer.get("expires_in") or 3600))
        refresh = str(answer.get("refresh_token") or previous_refresh or "")
        return TokenSet(
            access_token=str(answer["access_token"]),
            refresh_token=refresh,
            expires_at=self._now() + timedelta(seconds=lifetime),
            scope=str(answer.get("scope") or ""),
        )
