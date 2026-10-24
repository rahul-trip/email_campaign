"""Connecting and managing mailboxes from Settings (Phase 6c): OAuth with state and PKCE kept in
the session, IMAP after a test, and pausing, defaults, senders and disconnecting."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import Engine

from outbound.db.identity import IdentityUnitOfWorkFactory
from outbound.db.session import make_session_factory
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import MailboxGateway, MailboxStatus
from outbound.providers.adapters.imap_mailbox import ImapMailbox
from outbound.providers.errors import ProviderAuthError
from outbound.providers.oauth import TokenSet, google
from outbound.services.mailboxes import ImapSettings, MailboxError, MailboxService
from tests.providers.helpers import mock_client
from tests.providers.mail_fakes import FakeGmail

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
APPS = {MailboxGateway.GMAIL: google("g-client", "g-secret")}


class Google:
    """Google's token endpoint and the Gmail API, as one fake."""

    def __init__(self, *, grant_ok: bool = True) -> None:
        self.gmail = FakeGmail(valid_tokens={"at-new"})
        self.grant_ok = grant_ok
        self.revoked: list[str] = []
        self.token_forms: list[dict[str, list[str]]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == "oauth2.googleapis.com" and request.url.path == "/token":
            self.token_forms.append(parse_qs(request.content.decode()))
            if not self.grant_ok:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(
                200,
                json={
                    "access_token": "at-new",
                    "refresh_token": "rt-new",
                    "expires_in": 3600,
                    "scope": "gmail",
                },
            )
        if host == "oauth2.googleapis.com" and request.url.path == "/revoke":
            self.revoked.append(parse_qs(request.content.decode())["token"][0])
            return httpx.Response(200)
        if request.url.path.endswith("/profile"):
            if request.headers.get("authorization") != "Bearer at-new":
                return httpx.Response(401)
            return httpx.Response(200, json={"emailAddress": "Sam@Gmail.example"})
        return self.gmail(request)


@pytest.fixture
def identity(engine: Engine) -> IdentityUnitOfWorkFactory:
    return IdentityUnitOfWorkFactory(make_session_factory(engine))


@pytest.fixture
def session(identity: IdentityUnitOfWorkFactory) -> tuple[str, str]:
    with identity() as ids:
        user = ids.users.create("sam@quantra.example", "x")
        login = ids.sessions.create(user.id, "hash-1", NOW + timedelta(days=1))
        ids.commit()
    return user.id, login.id


def service(
    factory: UnitOfWorkFactory,
    identity: IdentityUnitOfWorkFactory,
    ws: str,
    server: Any = None,
    **kw: Any,
) -> MailboxService:
    return MailboxService(
        factory, identity, ws, apps=APPS, base_url="https://app.example",
        client=mock_client(server or Google()), now=kw.pop("now", lambda: NOW), **kw,
    )  # fmt: skip


def connect_gmail(svc: MailboxService, session: tuple[str, str]) -> Any:
    user_id, session_id = session
    url = svc.start_oauth(MailboxGateway.GMAIL, session_id=session_id, user_id=user_id)
    state = parse_qs(urlsplit(url).query)["state"][0]
    return svc.finish_oauth(session_id=session_id, code="code-1", state=state)


# ------------------------------------------------------------------ OAuth


def test_connecting_google_stores_the_tokens_sealed_and_makes_it_the_default(
    factory: UnitOfWorkFactory,
    identity: IdentityUnitOfWorkFactory,
    ws: str,
    session: tuple[str, str],
) -> None:
    server = Google()
    svc = service(factory, identity, ws, server)
    user_id, session_id = session
    url = svc.start_oauth(MailboxGateway.GMAIL, session_id=session_id, user_id=user_id)
    query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert query["redirect_uri"] == "https://app.example/oauth/callback"
    box = svc.finish_oauth(session_id=session_id, code="code-1", state=query["state"])
    assert (box.address, box.gateway, box.is_default, box.owner_user_id) == (
        "sam@gmail.example",
        MailboxGateway.GMAIL,
        True,
        user_id,
    )
    assert server.token_forms[0]["code_verifier"][0]  # the PKCE verifier went with the code
    with factory(ws) as uow:
        _, secret = uow.credentials.reveal(box.credentials_ref or "")
    assert TokenSet.model_validate_json(secret).refresh_token == "rt-new"
    with identity() as ids:
        assert "oauth" not in ids.sessions.data(session_id)  # the state is spent


def test_a_wrong_or_reused_state_is_refused(
    factory: UnitOfWorkFactory,
    identity: IdentityUnitOfWorkFactory,
    ws: str,
    session: tuple[str, str],
) -> None:
    svc = service(factory, identity, ws)
    user_id, session_id = session
    url = svc.start_oauth(MailboxGateway.GMAIL, session_id=session_id, user_id=user_id)
    state = parse_qs(urlsplit(url).query)["state"][0]
    with pytest.raises(MailboxError, match="not valid"):
        svc.finish_oauth(session_id=session_id, code="c", state="forged")
    with pytest.raises(MailboxError):  # the forged attempt also spent the real state
        svc.finish_oauth(session_id=session_id, code="c", state=state)
    assert svc.all() == []


def test_a_sign_in_that_took_too_long_or_belongs_elsewhere_is_refused(
    factory: UnitOfWorkFactory,
    identity: IdentityUnitOfWorkFactory,
    ws: str,
    other_ws: str,
    session: tuple[str, str],
) -> None:
    user_id, session_id = session
    started = service(factory, identity, ws)
    later = service(factory, identity, ws, now=lambda: NOW + timedelta(minutes=30))
    url = started.start_oauth(MailboxGateway.GMAIL, session_id=session_id, user_id=user_id)
    with pytest.raises(MailboxError, match="too long"):
        later.finish_oauth(
            session_id=session_id, code="c", state=parse_qs(urlsplit(url).query)["state"][0]
        )
    url = started.start_oauth(MailboxGateway.GMAIL, session_id=session_id, user_id=user_id)
    with pytest.raises(MailboxError, match="another workspace"):
        service(factory, identity, other_ws).finish_oauth(
            session_id=session_id, code="c", state=parse_qs(urlsplit(url).query)["state"][0]
        )


def test_a_provider_that_is_not_set_up_cannot_be_started(
    factory: UnitOfWorkFactory,
    identity: IdentityUnitOfWorkFactory,
    ws: str,
    session: tuple[str, str],
) -> None:
    svc = service(factory, identity, ws)
    assert svc.gateways() == [MailboxGateway.IMAP, MailboxGateway.GMAIL]
    with pytest.raises(MailboxError, match="not set up"):
        svc.start_oauth(MailboxGateway.GRAPH, session_id=session[1], user_id=session[0])


def test_connecting_the_same_account_again_reconnects_the_same_mailbox(
    factory: UnitOfWorkFactory,
    identity: IdentityUnitOfWorkFactory,
    ws: str,
    session: tuple[str, str],
) -> None:
    svc = service(factory, identity, ws)
    first = connect_gmail(svc, session)
    with factory(ws) as uow:
        uow.mailboxes.update(first.id, status=MailboxStatus.NEEDS_RECONNECT)
        uow.commit()
    again = connect_gmail(svc, session)
    assert again.id == first.id and again.status is MailboxStatus.ACTIVE
    with factory(ws) as uow:
        assert uow.credentials.get(again.credentials_ref or "").version == 2  # type: ignore[union-attr]


# ------------------------------------------------------------------ IMAP


class FakeCheck(ImapMailbox):
    def __init__(self, ok: bool) -> None:
        self.ok = ok

    def check(self) -> dict[str, str]:
        if not self.ok:
            raise ProviderAuthError("imap", "the server rejected the login")
        return {"drafts": "INBOX.Drafts", "sent": "INBOX.Sent"}


def test_an_imap_mailbox_is_saved_only_after_its_login_works(
    factory: UnitOfWorkFactory, identity: IdentityUnitOfWorkFactory, ws: str
) -> None:
    settings = ImapSettings(
        address="Sam@Quantra.example", host="IMAP.quantra.example", password="pw"
    )
    refused = service(factory, identity, ws, imap=lambda _: FakeCheck(False))
    with pytest.raises(MailboxError, match="refused that login"):
        refused.connect_imap(settings, owner_user_id=None)
    assert refused.all() == []
    box = service(factory, identity, ws, imap=lambda _: FakeCheck(True)).connect_imap(
        settings, owner_user_id=None
    )
    assert box.address == "sam@quantra.example" and box.gateway is MailboxGateway.IMAP
    assert box.connection == {
        "host": "imap.quantra.example",
        "port": 993,
        "username": None,
        "drafts_folder": "INBOX.Drafts",
        "sent_folder": "INBOX.Sent",
    }
    with factory(ws) as uow:
        assert uow.credentials.reveal(box.credentials_ref or "")[1] == "pw"


# ------------------------------------------------------------------ managing


def test_checking_a_mailbox_records_whether_it_works(
    factory: UnitOfWorkFactory,
    identity: IdentityUnitOfWorkFactory,
    ws: str,
    session: tuple[str, str],
) -> None:
    box = connect_gmail(service(factory, identity, ws), session)
    assert service(factory, identity, ws).test(box.id)["ok"] is True
    # access revoked at Google: the token is refused and the refresh too
    broken = Google(grant_ok=False)
    broken.gmail.valid_tokens = set()
    result = service(factory, identity, ws, broken).test(box.id)
    assert result == {
        "ok": False,
        "status": "needs_reconnect",
        "detail": "Access has run out. Connect it again.",
    }


def test_pausing_resuming_defaults_and_senders(
    factory: UnitOfWorkFactory,
    identity: IdentityUnitOfWorkFactory,
    ws: str,
    session: tuple[str, str],
) -> None:
    svc = service(factory, identity, ws, imap=lambda _: FakeCheck(True))
    gmail = connect_gmail(svc, session)
    imap = svc.connect_imap(
        ImapSettings(address="pat@quantra.example", host="imap.q.example", password="pw"),
        owner_user_id=None,
    )
    assert not imap.is_default
    assert svc.make_default(imap.id).is_default and not svc.get(gmail.id).is_default
    assert svc.pause(gmail.id).status is MailboxStatus.PAUSED
    assert svc.test(gmail.id)["status"] == "paused"  # a working, paused mailbox stays paused
    assert svc.resume(gmail.id).status is MailboxStatus.ACTIVE
    updated = svc.set_sender(
        gmail.id, {"signature_name": "Sam Lee", "legal_name": "not a person field"}
    )
    assert updated.sender == {"signature_name": "Sam Lee"}


def test_disconnecting_removes_the_secret_and_moves_the_default(
    factory: UnitOfWorkFactory,
    identity: IdentityUnitOfWorkFactory,
    ws: str,
    session: tuple[str, str],
) -> None:
    server = Google()
    svc = service(factory, identity, ws, server, imap=lambda _: FakeCheck(True))
    gmail = connect_gmail(svc, session)
    imap = svc.connect_imap(
        ImapSettings(address="pat@quantra.example", host="imap.q.example", password="pw"),
        owner_user_id=None,
    )
    with factory(ws) as uow:
        campaign = uow.campaigns.create("c", ["CTO"])
        uow.campaigns.update(campaign.id, {"mailbox_id": gmail.id})
        uow.commit()
    svc.disconnect(gmail.id)
    assert server.revoked == ["rt-new"]  # Google was told the grant is no longer wanted
    assert [b.id for b in svc.all()] == [imap.id] and svc.get(imap.id).is_default
    with factory(ws) as uow:
        assert uow.credentials.get(gmail.credentials_ref or "") is None
        assert uow.campaigns.get(campaign.id).mailbox_id is None
    assert json.dumps([b.address for b in svc.all()]) == '["pat@quantra.example"]'


def test_an_imap_mailbox_needs_a_real_address(
    factory: UnitOfWorkFactory, identity: IdentityUnitOfWorkFactory, ws: str
) -> None:
    svc = service(factory, identity, ws, imap=lambda _: FakeCheck(True))
    with pytest.raises(MailboxError, match="full email address"):
        svc.connect_imap(
            ImapSettings(address="not-an-address", host="h.example", password="pw"),
            owner_user_id=None,
        )
