"""The mailboxes a workspace has connected, opened when a stage or job needs one (Phase 6c).

``StoredMailboxes`` reads a mailbox's row and credential (each in its own short transaction)
and builds the adapter for its gateway: IMAP with its app password, Microsoft Graph or the
Gmail API with OAuth tokens that ``StoredTokens`` keeps fresh. A mailbox that is paused, or
whose access has run out (``needs_reconnect``), is not opened: the work that needs it waits.

``one(mailbox)`` serves a single, already built mailbox (tests and scripts).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

import httpx

from outbound.db.repositories.workspaces import MailboxView
from outbound.db.types import utcnow
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import MailboxGateway, MailboxStatus
from outbound.logging import get_logger
from outbound.providers.adapters.gmail_api import GmailMailbox
from outbound.providers.adapters.imap_mailbox import ImapMailbox
from outbound.providers.adapters.ms_graph import GraphMailbox
from outbound.providers.errors import ProviderError, ReconnectNeeded
from outbound.providers.oauth import OAuthApp, OAuthClient, TokenSet
from outbound.providers.ports import Mailbox

log = get_logger(__name__)


class MailboxUnavailable(Exception):
    """No mailbox can be used for this right now; the work waits and is tried again later."""


class Mailboxes(Protocol):
    def open(self, mailbox_id: str | None) -> tuple[str | None, Mailbox]:
        """The mailbox (``None``: the workspace's default) and its id, ready to use."""
        ...

    def all_open(self) -> list[tuple[str | None, Mailbox]]:
        """Every mailbox that can be used now."""
        ...


@dataclass(frozen=True)
class One:
    """A single mailbox, already built."""

    mailbox: Mailbox
    mailbox_id: str | None = None

    def open(self, mailbox_id: str | None) -> tuple[str | None, Mailbox]:
        return self.mailbox_id, self.mailbox

    def all_open(self) -> list[tuple[str | None, Mailbox]]:
        return [(self.mailbox_id, self.mailbox)]


def one(mailbox: Mailbox, mailbox_id: str | None = None) -> One:
    return One(mailbox, mailbox_id)


class StoredTokens:
    """A mailbox's OAuth tokens, stored sealed in its credential and refreshed when needed.

    The refresh happens outside any transaction; the new tokens are written only if the
    credential is still at the version that was read (compare-and-swap). If another worker
    refreshed first, its tokens are used and ours are dropped, so a rotated refresh token is
    never overwritten with a stale one.
    """

    def __init__(
        self,
        uow: UnitOfWorkFactory,
        workspace_id: str,
        mailbox_id: str,
        credential: str,
        oauth: OAuthClient,
        *,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._uow = uow
        self._workspace_id = workspace_id
        self._mailbox_id = mailbox_id
        self._credential = credential
        self._oauth = oauth
        self._now = now

    def current(self) -> str:
        tokens, version = self._read()
        if tokens.expiring(self._now()):
            return self._refresh(tokens, version)
        return tokens.access_token

    def renew(self) -> str:
        tokens, version = self._read()
        return self._refresh(tokens, version)

    def _read(self) -> tuple[TokenSet, int]:
        with self._uow(self._workspace_id) as uow:
            found, secret = uow.credentials.reveal(self._credential)
        return TokenSet.model_validate_json(secret), found.version

    def _refresh(self, tokens: TokenSet, version: int) -> str:
        try:
            fresh = self._oauth.refresh(tokens.refresh_token)
        except ReconnectNeeded:
            mark(self._uow, self._workspace_id, self._mailbox_id, MailboxStatus.NEEDS_RECONNECT)
            raise
        with self._uow(self._workspace_id) as uow:
            won = uow.credentials.swap(
                self._credential, version, fresh.model_dump_json(), expires_at=fresh.expires_at
            )
            uow.commit()
        if won:
            return fresh.access_token
        winner, _ = self._read()  # another worker refreshed at the same moment: use theirs
        return winner.access_token


def mark(uow: UnitOfWorkFactory, workspace_id: str, mailbox_id: str, status: MailboxStatus) -> None:
    with uow(workspace_id) as session:
        session.mailboxes.update(mailbox_id, status=status, last_checked_at=utcnow())
        session.commit()
    if status is not MailboxStatus.ACTIVE:
        log.warning("mailbox_unavailable", mailbox_id=mailbox_id, status=status.value)


@dataclass
class StoredMailboxes:
    uow: UnitOfWorkFactory
    workspace_id: str
    apps: dict[MailboxGateway, OAuthApp] = field(default_factory=dict)
    client: httpx.Client | None = None  # tests pass a fake server; real runs use their own
    timeout: float = 30.0

    def open(self, mailbox_id: str | None) -> tuple[str | None, Mailbox]:
        with self.uow(self.workspace_id) as uow:
            view = uow.mailboxes.get(mailbox_id) if mailbox_id else uow.mailboxes.default()
        if view is None:
            raise MailboxUnavailable("no mailbox is connected: connect one in Settings")
        if view.status is not MailboxStatus.ACTIVE:
            raise MailboxUnavailable(
                f"the mailbox {view.address} is {view.status.value.replace('_', ' ')}"
            )
        return view.id, self.build(view)

    def all_open(self) -> list[tuple[str | None, Mailbox]]:
        with self.uow(self.workspace_id) as uow:
            views = [v for v in uow.mailboxes.all() if v.status is MailboxStatus.ACTIVE]
        opened: list[tuple[str | None, Mailbox]] = []
        for view in views:
            try:
                opened.append((view.id, self.build(view)))
            except (MailboxUnavailable, ProviderError) as error:
                log.warning("mailbox_not_opened", mailbox_id=view.id, reason=str(error)[:200])
        return opened

    def tokens_for(self, view: MailboxView) -> StoredTokens:
        app = self.apps.get(view.gateway)
        if app is None or not app.configured:
            raise MailboxUnavailable(f"{view.gateway.value} sign-in is not set up on this server")
        if not view.credentials_ref:
            raise MailboxUnavailable(f"the mailbox {view.address} is not connected yet")
        return StoredTokens(
            self.uow, self.workspace_id, view.id, view.credentials_ref,
            OAuthClient(app, client=self.client),
        )  # fmt: skip

    def build(self, view: MailboxView) -> Mailbox:
        if not view.credentials_ref:
            raise MailboxUnavailable(f"the mailbox {view.address} is not connected yet")
        sender = view.sender or {}
        if view.gateway is MailboxGateway.IMAP:
            with self.uow(self.workspace_id) as uow:
                _, password = uow.credentials.reveal(view.credentials_ref)
            conn = view.connection or {}
            return ImapMailbox(
                host=str(conn.get("host") or ""),
                port=int(conn.get("port") or 993),
                username=conn.get("username") or None,
                address=view.address,
                password=password,
                from_name=str(sender.get("signature_name") or ""),
                drafts_folder=conn.get("drafts_folder") or None,
                sent_folder=conn.get("sent_folder") or None,
                timeout=self.timeout,
            )
        tokens = self.tokens_for(view)
        if view.gateway is MailboxGateway.GRAPH:
            return GraphMailbox(view.address, tokens, client=self.client)
        if view.gateway is MailboxGateway.GMAIL:
            return GmailMailbox(
                view.address, tokens, from_name=str(sender.get("signature_name") or ""),
                client=self.client,
            )  # fmt: skip
        raise MailboxUnavailable(f"{view.gateway.value} mailboxes are not supported")


@dataclass
class MailboxHealth:
    """Part of the tick: refresh OAuth tokens that are about to run out, so a revoked or
    expired grant is found (and the mailbox marked ``needs_reconnect``) before a draft needs it.
    """

    mailboxes: StoredMailboxes
    name: str = "mailbox_health"

    def run(self) -> dict[str, int]:
        store = self.mailboxes
        with store.uow(store.workspace_id) as uow:
            views = [
                v for v in uow.mailboxes.all()
                if v.status is MailboxStatus.ACTIVE and v.gateway is not MailboxGateway.IMAP
            ]  # fmt: skip
        counts = {"checked": 0, "needs_reconnect": 0, "failed": 0}
        for view in views:
            try:
                tokens = store.tokens_for(view)
                tokens.current()
                counts["checked"] += 1
                with store.uow(store.workspace_id) as uow:
                    uow.mailboxes.update(view.id, last_checked_at=utcnow())
                    uow.commit()
            except ReconnectNeeded:
                counts["needs_reconnect"] += 1  # StoredTokens has marked it already
            except (MailboxUnavailable, ProviderError) as error:
                counts["failed"] += 1
                log.warning("mailbox_check_failed", mailbox_id=view.id, reason=str(error)[:200])
        return counts
