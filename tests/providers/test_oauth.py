"""OAuth for connected mailboxes (Phase 6c): PKCE, the authorization link, exchanging the code
and refreshing, against the token endpoints' documented answers."""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from outbound.providers.errors import ProviderError, ReconnectNeeded
from outbound.providers.oauth import (
    GOOGLE_SCOPES,
    OAuthClient,
    TokenSet,
    authorization_url,
    google,
    microsoft,
    pkce_pair,
)
from tests.providers.helpers import Handler, mock_client

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
MS = microsoft("ms-client", "ms-secret")
GOOGLE = google("g-client", "g-secret")


def token_endpoint(
    answer: dict[str, object], status: int = 200, seen: list[dict[str, list[str]]] | None = None
) -> Handler:
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(parse_qs(request.content.decode()))
        return httpx.Response(status, json=answer)

    return handle


def test_the_pkce_challenge_is_the_s256_of_the_verifier() -> None:
    verifier, challenge = pkce_pair()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    assert challenge == expected.decode() and 43 <= len(verifier) <= 128
    assert pkce_pair()[0] != verifier


def test_the_authorization_link_asks_for_offline_access_with_pkce() -> None:
    url = authorization_url(
        GOOGLE,
        redirect_uri="https://app.example/oauth/callback",
        state="s1",
        challenge="c1",
        login_hint="sam@x.com",
    )
    parts = urlsplit(url)
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert parts.netloc == "accounts.google.com"
    assert query["scope"].split() == list(GOOGLE_SCOPES)
    assert (query["state"], query["code_challenge"], query["code_challenge_method"]) == (
        "s1",
        "c1",
        "S256",
    )
    assert (query["access_type"], query["prompt"], query["login_hint"]) == (
        "offline",
        "consent",
        "sam@x.com",
    )
    ms = {
        k: v[0]
        for k, v in parse_qs(
            urlsplit(authorization_url(MS, redirect_uri="r", state="s", challenge="c")).query
        ).items()
    }
    assert "offline_access" in ms["scope"].split() and "Mail.ReadWrite" in ms["scope"].split()


def test_the_code_is_exchanged_with_its_verifier() -> None:
    seen: list[dict[str, list[str]]] = []
    answer = {
        "access_token": "at",
        "refresh_token": "rt",
        "expires_in": 3599,
        "scope": "Mail.ReadWrite",
    }
    client = OAuthClient(MS, client=mock_client(token_endpoint(answer, seen=seen)), now=lambda: NOW)
    tokens = client.exchange("code-1", "verifier-1", "https://app.example/oauth/callback")
    assert tokens == TokenSet(
        access_token="at",
        refresh_token="rt",
        expires_at=NOW + timedelta(seconds=3599),
        scope="Mail.ReadWrite",
    )
    [form] = seen
    assert form["grant_type"] == ["authorization_code"] and form["code_verifier"] == ["verifier-1"]
    assert form["client_secret"] == ["ms-secret"]


def test_an_exchange_without_a_refresh_token_is_refused() -> None:
    client = OAuthClient(
        GOOGLE, client=mock_client(token_endpoint({"access_token": "at", "expires_in": 3600}))
    )
    with pytest.raises(ProviderError, match="no refresh token"):
        client.exchange("code", "verifier", "r")


def test_microsoft_rotates_the_refresh_token_and_google_keeps_the_old_one() -> None:
    rotated = OAuthClient(
        MS,
        client=mock_client(
            token_endpoint({"access_token": "at2", "refresh_token": "rt2", "expires_in": 3600})
        ),
        now=lambda: NOW,
    )
    assert rotated.refresh("rt1").refresh_token == "rt2"
    kept = OAuthClient(
        GOOGLE,
        client=mock_client(token_endpoint({"access_token": "at2", "expires_in": 3600})),
        now=lambda: NOW,
    )
    assert kept.refresh("rt1").refresh_token == "rt1"


def test_a_revoked_grant_means_connect_again() -> None:
    client = OAuthClient(
        GOOGLE, client=mock_client(token_endpoint({"error": "invalid_grant"}, status=400))
    )
    with pytest.raises(ReconnectNeeded):
        client.refresh("rt1")


def test_a_token_counts_as_expiring_a_few_minutes_early() -> None:
    tokens = TokenSet(access_token="a", refresh_token="r", expires_at=NOW + timedelta(minutes=4))
    assert tokens.expiring(NOW) and not tokens.expiring(NOW - timedelta(minutes=10))
