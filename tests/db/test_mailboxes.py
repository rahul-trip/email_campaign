"""Connected mailboxes in the engine (Phase 6c): the copy stage picks the sender, delivery waits
for a mailbox that cannot be used, tokens refresh safely, and each mailbox is opened with its own
credential."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine

from outbound.bootstrap import container_for
from outbound.config import Settings
from outbound.db.models import WorkspaceRow
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import CompanyStatus, CredentialPurpose, MailboxGateway, MailboxStatus
from outbound.domain.policy_seeds import DEFAULT_COUNTRY_POLICIES
from outbound.pipeline import assemble
from outbound.providers.adapters.gmail_api import GmailMailbox
from outbound.providers.adapters.imap_mailbox import ImapMailbox
from outbound.providers.errors import ReconnectNeeded
from outbound.providers.oauth import OAuthClient, TokenSet, google
from outbound.stages.mailboxes import MailboxUnavailable, StoredMailboxes, StoredTokens
from tests.providers.helpers import mock_client
from tests.stages.world import PROFILE, World

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
GOOGLE = google("g-client", "g-secret")


def prepared(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        for policy in DEFAULT_COUNTRY_POLICIES:
            uow.policies.add_if_missing(policy)
        row = uow.session.get(WorkspaceRow, ws)
        assert row is not None
        row.sender_profile = PROFILE
        uow.campaigns.create("default", ["CTO"], icp_description="Utilities")
        uow.commit()


def add_box(
    factory: UnitOfWorkFactory,
    ws: str,
    address: str,
    *,
    gateway: MailboxGateway = MailboxGateway.IMAP,
    secret: str = "app-password",  # noqa: S107  (a test value)
    status: MailboxStatus = MailboxStatus.ACTIVE,
    **fields: object,
) -> str:
    with factory(ws) as uow:
        box = uow.mailboxes.create(address, address.rpartition("@")[2], gateway=gateway, **fields)  # type: ignore[arg-type]
        purpose = (
            CredentialPurpose.MAILBOX_PASSWORD
            if gateway is MailboxGateway.IMAP
            else CredentialPurpose.MAILBOX_OAUTH
        )
        uow.credentials.put(f"mailbox:{box.id}", purpose, secret)
        uow.mailboxes.update(box.id, credentials_ref=f"mailbox:{box.id}", status=status)
        uow.commit()
    return box.id


# ------------------------------------------------------------------ choosing the sender


def test_the_email_is_signed_by_the_default_mailboxes_person_and_remembers_the_mailbox(
    engine: Engine, factory: UnitOfWorkFactory, ws: str
) -> None:
    prepared(factory, ws)
    box = add_box(
        factory, ws, "pat@quantra.example",
        sender={"signature_name": "Pat Kim", "signature_title": "Head of Sales"},
    )  # fmt: skip
    world = World()
    pipeline = assemble(container_for(Settings(_env_file=None), engine), ws, world.providers())
    pipeline.intake.run([{"Website": "acme.co.uk", "Company": "Acme", "Country": "UK"}])
    pipeline.runner.run_pipeline()
    [queued] = pipeline.review.queue()
    assert queued.message.mailbox_id == box
    assert (
        "Pat Kim" in queued.message.generated_body
        and "Head of Sales" in queued.message.generated_body
    )
    assert "Sam Lee" not in queued.message.generated_body


def test_a_campaign_can_send_from_its_own_mailbox(
    engine: Engine, factory: UnitOfWorkFactory, ws: str
) -> None:
    prepared(factory, ws)
    add_box(factory, ws, "sales@quantra.example")  # the default
    other = add_box(factory, ws, "pat@quantra.example", sender={"signature_name": "Pat Kim"})
    with factory(ws) as uow:
        campaign = uow.campaigns.by_name("default")
        assert campaign is not None
        uow.campaigns.update(campaign.id, {"mailbox_id": other})
        uow.commit()
    world = World()
    pipeline = assemble(container_for(Settings(_env_file=None), engine), ws, world.providers())
    pipeline.intake.run(
        [{"Website": "acme.co.uk", "Company": "Acme", "Country": "UK"}], campaign_id=campaign.id
    )
    pipeline.runner.run_pipeline()
    [queued] = pipeline.review.queue()
    assert queued.message.mailbox_id == other
    assert "Pat Kim" in queued.message.generated_body
    assert "CPO, Quantra" in queued.message.generated_body  # the title still comes from the profile


# ------------------------------------------------------------------ opening a mailbox


def test_each_mailbox_opens_with_its_own_password_and_settings(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    box = add_box(
        factory, ws, "sam@quantra.example", secret="pw-1",
        connection={"host": "imap.quantra.example", "port": 993, "drafts_folder": "INBOX.Drafts"},
        sender={"signature_name": "Sam Lee"},
    )  # fmt: skip
    mailbox_id, opened = StoredMailboxes(factory, ws).open(None)
    assert mailbox_id == box and isinstance(opened, ImapMailbox)
    assert opened.address == "sam@quantra.example"
    assert opened._password == "pw-1" and opened._from_name == "Sam Lee"
    assert opened._folders["drafts"] == "INBOX.Drafts"


@pytest.mark.parametrize("status", [MailboxStatus.PAUSED, MailboxStatus.NEEDS_RECONNECT])
def test_a_paused_or_disconnected_mailbox_is_not_opened(
    factory: UnitOfWorkFactory, ws: str, status: MailboxStatus
) -> None:
    add_box(factory, ws, "sam@quantra.example", status=status)
    with pytest.raises(MailboxUnavailable, match=status.value.replace("_", " ")):
        StoredMailboxes(factory, ws).open(None)
    assert StoredMailboxes(factory, ws).all_open() == []


def test_without_any_mailbox_the_work_waits(factory: UnitOfWorkFactory, ws: str) -> None:
    with pytest.raises(MailboxUnavailable, match="no mailbox is connected"):
        StoredMailboxes(factory, ws).open(None)


def test_a_google_mailbox_needs_the_sign_in_app_set_up(factory: UnitOfWorkFactory, ws: str) -> None:
    tokens = TokenSet(
        access_token="at-1", refresh_token="rt-1", expires_at=NOW + timedelta(hours=1)
    )
    add_box(
        factory,
        ws,
        "sam@gmail.example",
        gateway=MailboxGateway.GMAIL,
        secret=tokens.model_dump_json(),
    )
    with pytest.raises(MailboxUnavailable, match="not set up"):
        StoredMailboxes(factory, ws).open(None)
    _, opened = StoredMailboxes(factory, ws, apps={MailboxGateway.GMAIL: GOOGLE}).open(None)
    assert isinstance(opened, GmailMailbox)


def test_delivery_waits_while_the_mailbox_needs_reconnecting(
    engine: Engine, factory: UnitOfWorkFactory, ws: str
) -> None:
    prepared(factory, ws)
    box = add_box(factory, ws, "sam@quantra.example", status=MailboxStatus.NEEDS_RECONNECT)
    container = container_for(Settings(_env_file=None), engine)
    providers = World().providers()
    pipeline = assemble(
        container, ws, providers.__class__(**{**providers.__dict__, "mailbox": None})
    )
    pipeline.intake.run([{"Website": "acme.co.uk", "Company": "Acme", "Country": "UK"}])
    pipeline.runner.run_pipeline()
    [queued] = pipeline.review.queue()
    pipeline.review.approve(queued.message.id)
    pipeline.runner.run_pipeline()
    with factory(ws) as uow:
        company = uow.companies.get(queued.company.id)
    assert company.status is CompanyStatus.APPROVED  # waiting, not failed
    assert company.next_action_at is not None
    assert box  # reconnecting later lets the next run deliver


# ------------------------------------------------------------------ refreshing tokens


def oauth(
    answer: dict[str, object], status: int = 200, calls: list[int] | None = None
) -> OAuthClient:
    def handle(_: object) -> object:
        import httpx

        if calls is not None:
            calls.append(1)
        return httpx.Response(status, json=answer)

    return OAuthClient(GOOGLE, client=mock_client(handle), now=lambda: NOW)  # type: ignore[arg-type]


def stored_tokens(factory: UnitOfWorkFactory, ws: str, expires_in: timedelta) -> tuple[str, str]:
    tokens = TokenSet(access_token="at-1", refresh_token="rt-1", expires_at=NOW + expires_in)
    box = add_box(
        factory,
        ws,
        "sam@gmail.example",
        gateway=MailboxGateway.GMAIL,
        secret=tokens.model_dump_json(),
    )
    return box, f"mailbox:{box}"


def test_a_fresh_token_is_used_as_it_is(factory: UnitOfWorkFactory, ws: str) -> None:
    box, name = stored_tokens(factory, ws, timedelta(hours=1))
    calls: list[int] = []
    tokens = StoredTokens(factory, ws, box, name, oauth({}, calls=calls), now=lambda: NOW)
    assert tokens.current() == "at-1" and calls == []


def test_an_expiring_token_is_refreshed_and_stored(factory: UnitOfWorkFactory, ws: str) -> None:
    box, name = stored_tokens(factory, ws, timedelta(minutes=2))
    refreshed = oauth({"access_token": "at-2", "expires_in": 3600})
    assert StoredTokens(factory, ws, box, name, refreshed, now=lambda: NOW).current() == "at-2"
    with factory(ws) as uow:
        found, secret = uow.credentials.reveal(name)
    stored = json.loads(secret)
    assert (stored["access_token"], stored["refresh_token"], found.version) == ("at-2", "rt-1", 2)


def test_two_workers_refresh_at_once_and_both_end_with_the_winners_token(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    box, name = stored_tokens(factory, ws, timedelta(minutes=2))
    slow = StoredTokens(
        factory,
        ws,
        box,
        name,
        oauth({"access_token": "at-slow", "refresh_token": "rt-slow", "expires_in": 3600}),
        now=lambda: NOW,
    )
    fast = StoredTokens(
        factory,
        ws,
        box,
        name,
        oauth({"access_token": "at-fast", "refresh_token": "rt-fast", "expires_in": 3600}),
        now=lambda: NOW,
    )
    tokens, version = slow._read()
    assert fast.renew() == "at-fast"
    assert slow._refresh(tokens, version) == "at-fast"
    with factory(ws) as uow:
        _, secret = uow.credentials.reveal(name)
    assert json.loads(secret)["refresh_token"] == "rt-fast"  # the rotated token was not lost


def test_a_revoked_grant_marks_the_mailbox_for_reconnecting(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    box, name = stored_tokens(factory, ws, timedelta(minutes=2))
    refused = oauth({"error": "invalid_grant"}, status=400)
    with pytest.raises(ReconnectNeeded):
        StoredTokens(factory, ws, box, name, refused, now=lambda: NOW).current()
    with factory(ws) as uow:
        assert uow.mailboxes.get(box).status is MailboxStatus.NEEDS_RECONNECT
