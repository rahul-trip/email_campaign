"""Connecting and managing a workspace's mailboxes, from Settings only (Phase 6c).

- **Microsoft 365 and Google** connect with OAuth: ``start_oauth`` gives the link to the
  provider and keeps the ``state`` and PKCE verifier in the person's session row;
  ``finish_oauth`` checks them, exchanges the code (outside any transaction), finds the
  account's address and stores the tokens sealed.
- **Any IMAP account** connects with a host and an app password, after a test that signs in
  and finds the Drafts and Sent folders.
- Connecting an address the workspace already has reconnects it: same mailbox, new secret.

Every change is one short transaction; network calls happen between them.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx

from outbound.db.errors import NotFound
from outbound.db.identity import IdentityUnitOfWorkFactory
from outbound.db.repositories.workspaces import MailboxView
from outbound.db.types import utcnow
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import CredentialPurpose, MailboxGateway, MailboxStatus
from outbound.domain.sender import person_of
from outbound.logging import get_logger
from outbound.providers.adapters import gmail_api, ms_graph
from outbound.providers.adapters.imap_mailbox import ImapMailbox
from outbound.providers.errors import ProviderAuthError, ProviderError, ReconnectNeeded
from outbound.providers.oauth import OAuthApp, OAuthClient, TokenSet, authorization_url, pkce_pair
from outbound.stages.mailboxes import MailboxUnavailable, StoredMailboxes

log = get_logger(__name__)

OAUTH_WINDOW = timedelta(minutes=15)  # from "Connect" to coming back from the provider
HEALTH_PROBE = "<outbound-connection-check@localhost>"


class MailboxError(Exception):
    """Refused, with a reason a person can act on. ``status`` and ``code`` are for the API."""

    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


@dataclass(frozen=True)
class ImapSettings:
    address: str
    host: str
    password: str
    port: int = 993
    username: str | None = None
    drafts_folder: str | None = None
    sent_folder: str | None = None


ImapFactory = Callable[[ImapSettings], ImapMailbox]


def _imap(settings: ImapSettings) -> ImapMailbox:
    return ImapMailbox(
        host=settings.host, port=settings.port, username=settings.username,
        address=settings.address, password=settings.password,
        drafts_folder=settings.drafts_folder, sent_folder=settings.sent_folder,
    )  # fmt: skip


class MailboxService:
    def __init__(
        self,
        uow: UnitOfWorkFactory,
        identity: IdentityUnitOfWorkFactory,
        workspace_id: str,
        *,
        apps: dict[MailboxGateway, OAuthApp],
        base_url: str,
        client: httpx.Client | None = None,
        imap: ImapFactory = _imap,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._uow = uow
        self._identity = identity
        self._workspace_id = workspace_id
        self._apps = apps
        self._redirect = base_url.rstrip("/") + "/oauth/callback"
        self._client = client
        self._imap = imap
        self._now = now
        self._stored = StoredMailboxes(uow, workspace_id, apps=apps, client=client)

    # ------------------------------------------------------------------ reading

    def all(self) -> list[MailboxView]:
        with self._uow(self._workspace_id) as uow:
            return uow.mailboxes.all()

    def get(self, mailbox_id: str) -> MailboxView:
        with self._uow(self._workspace_id) as uow:
            return uow.mailboxes.get(mailbox_id)

    def gateways(self) -> list[MailboxGateway]:
        """What can be connected on this server: IMAP always, the others when set up."""
        return [MailboxGateway.IMAP, *(g for g, app in self._apps.items() if app.configured)]

    # ------------------------------------------------------------------ OAuth

    def start_oauth(
        self,
        gateway: MailboxGateway,
        *,
        session_id: str,
        user_id: str,
        login_hint: str | None = None,
    ) -> str:
        """The provider's sign-in link. The state and verifier wait in the session row."""
        app = self._app(gateway)
        verifier, challenge = pkce_pair()
        state = secrets.token_urlsafe(32)
        with self._identity() as ids:
            data = ids.sessions.data(session_id)
            data["oauth"] = {
                "state": state, "verifier": verifier, "gateway": gateway.value,
                "workspace_id": self._workspace_id, "user_id": user_id,
                "started_at": self._now().isoformat(),
            }  # fmt: skip
            ids.sessions.set_data(session_id, data)
            ids.commit()
        return authorization_url(
            app,
            redirect_uri=self._redirect,
            state=state,
            challenge=challenge,
            login_hint=login_hint,
        )

    def finish_oauth(self, *, session_id: str, code: str, state: str) -> MailboxView:
        """Back from the provider: check the state, exchange the code, store the tokens."""
        with self._identity() as ids:
            data = ids.sessions.data(session_id)
            pending = data.pop("oauth", None)
            ids.sessions.set_data(session_id, data)  # a state is used once, whatever happens
            ids.commit()
        if not pending or not secrets.compare_digest(str(pending.get("state", "")), state):
            raise MailboxError(400, "oauth_state", "This sign-in link is not valid. Start again.")
        if pending.get("workspace_id") != self._workspace_id:
            raise MailboxError(400, "oauth_state", "This sign-in was started in another workspace.")
        started = datetime.fromisoformat(str(pending["started_at"]))
        if self._now() - started > OAUTH_WINDOW:
            raise MailboxError(400, "oauth_expired", "The sign-in took too long. Start again.")
        gateway = MailboxGateway(str(pending["gateway"]))
        client = OAuthClient(self._app(gateway), client=self._client, now=self._now)
        try:
            tokens = client.exchange(code, str(pending["verifier"]), self._redirect)
            address = self._account(gateway, tokens.access_token)
        except ProviderError as error:
            log.warning("oauth_connect_failed", gateway=gateway.value, reason=str(error)[:200])
            raise MailboxError(
                502, "oauth_failed", "The provider did not accept the sign-in. Try again."
            ) from None
        return self._save(
            address, gateway, CredentialPurpose.MAILBOX_OAUTH, tokens.model_dump_json(),
            owner_user_id=str(pending.get("user_id") or "") or None,
            expires_at=tokens.expires_at, details={"scope": tokens.scope},
        )  # fmt: skip

    def _account(self, gateway: MailboxGateway, access_token: str) -> str:
        if gateway is MailboxGateway.GRAPH:
            return ms_graph.account_address(access_token, client=self._client)
        return gmail_api.account_address(access_token, client=self._client)

    def _app(self, gateway: MailboxGateway) -> OAuthApp:
        app = self._apps.get(gateway)
        if app is None or not app.configured:
            raise MailboxError(
                400, "not_available", "Signing in with this provider is not set up on this server."
            )
        return app

    # ------------------------------------------------------------------ IMAP

    def connect_imap(self, settings: ImapSettings, *, owner_user_id: str | None) -> MailboxView:
        """Test the login and the folders, then save the mailbox with its password sealed."""
        if "@" not in settings.address.strip()[1:-1]:
            raise MailboxError(422, "bad_address", "Give the mailbox's full email address.")
        try:
            folders = self._imap(settings).check()
        except ProviderAuthError:
            raise MailboxError(
                400,
                "imap_login",
                "The server refused that login. Check the user name and app password.",
            ) from None
        except ProviderError as error:
            raise MailboxError(
                400, "imap_failed", f"Could not use the server: {_plain(error)}"
            ) from None
        return self._save(
            settings.address, MailboxGateway.IMAP,
            CredentialPurpose.MAILBOX_PASSWORD, settings.password,
            owner_user_id=owner_user_id,
            connection={
                "host": settings.host.strip().lower(), "port": settings.port,
                "username": settings.username or None,
                "drafts_folder": folders["drafts"], "sent_folder": folders["sent"],
            },
        )  # fmt: skip

    # ------------------------------------------------------------------ managing

    def test(self, mailbox_id: str) -> dict[str, Any]:
        """Use the mailbox once (look for a draft that is never there) and record the result."""
        view = self.get(mailbox_id)
        status, detail = MailboxStatus.ACTIVE, "Connected and working."
        try:
            self._stored.build(view).draft_exists(HEALTH_PROBE)
        except ReconnectNeeded:
            status, detail = MailboxStatus.NEEDS_RECONNECT, "Access has run out. Connect it again."
        except ProviderAuthError:
            status, detail = MailboxStatus.ERROR, "The mailbox refused the login."
        except (ProviderError, MailboxUnavailable) as error:
            status, detail = MailboxStatus.ERROR, _plain(error)
        if view.status is MailboxStatus.PAUSED and status is MailboxStatus.ACTIVE:
            status = MailboxStatus.PAUSED  # a working mailbox someone paused stays paused
        with self._uow(self._workspace_id) as uow:
            uow.mailboxes.update(mailbox_id, status=status, last_checked_at=self._now())
            uow.commit()
        return {
            "ok": status in (MailboxStatus.ACTIVE, MailboxStatus.PAUSED),
            "status": status.value,
            "detail": detail,
        }

    def pause(self, mailbox_id: str) -> MailboxView:
        return self._set_status(mailbox_id, MailboxStatus.PAUSED)

    def resume(self, mailbox_id: str) -> MailboxView:
        view = self._set_status(mailbox_id, MailboxStatus.ACTIVE)
        self.test(mailbox_id)  # resuming one that cannot be used shows why at once
        return self.get(view.id)

    def make_default(self, mailbox_id: str) -> MailboxView:
        with self._uow(self._workspace_id) as uow:
            view = uow.mailboxes.make_default(mailbox_id)
            uow.commit()
        return view

    def set_sender(self, mailbox_id: str, sender: dict[str, Any]) -> MailboxView:
        """Who signs from this mailbox: name, title, greeting, style examples."""
        with self._uow(self._workspace_id) as uow:
            view = uow.mailboxes.update(mailbox_id, sender=person_of(sender) or None)
            uow.commit()
        return view

    def disconnect(self, mailbox_id: str) -> None:
        """Forget the mailbox and its secret. Its drafts stay in the mailbox; campaigns that sent
        from it fall back to the default mailbox."""
        view = self.get(mailbox_id)
        if view.gateway is MailboxGateway.GMAIL and view.credentials_ref:
            self._revoke_google(view.credentials_ref)
        with self._uow(self._workspace_id) as uow:
            if view.credentials_ref:
                uow.credentials.delete(view.credentials_ref)
            uow.mailboxes.delete(mailbox_id)
            uow.commit()
        log.info("mailbox_disconnected", mailbox_id=mailbox_id, gateway=view.gateway.value)

    def _revoke_google(self, credential: str) -> None:
        """Tell Google the grant is no longer wanted. Best effort: the secret goes either way."""
        try:
            with self._uow(self._workspace_id) as uow:
                _, secret = uow.credentials.reveal(credential)
            token = TokenSet.model_validate_json(secret).refresh_token
            client = self._client or httpx.Client(timeout=10)
            client.post("https://oauth2.googleapis.com/revoke", data={"token": token})
        except (httpx.HTTPError, ValueError, NotFound) as error:
            log.warning("oauth_revoke_failed", reason=type(error).__name__)

    def _set_status(self, mailbox_id: str, status: MailboxStatus) -> MailboxView:
        with self._uow(self._workspace_id) as uow:
            view = uow.mailboxes.update(mailbox_id, status=status)
            uow.commit()
        return view

    def _save(
        self,
        address: str,
        gateway: MailboxGateway,
        purpose: CredentialPurpose,
        secret: str,
        *,
        owner_user_id: str | None,
        connection: dict[str, Any] | None = None,
        expires_at: datetime | None = None,
        details: dict[str, Any] | None = None,
    ) -> MailboxView:
        address = address.strip().lower()
        with self._uow(self._workspace_id) as uow:
            existing = uow.mailboxes.by_address(address)
            if existing is None:
                existing = uow.mailboxes.create(
                    address, address.rpartition("@")[2], gateway=gateway,
                    owner_user_id=owner_user_id, connection=connection,
                )  # fmt: skip
            name = f"mailbox:{existing.id}"
            uow.credentials.put(name, purpose, secret, expires_at=expires_at, details=details)
            changes: dict[str, Any] = {
                "credentials_ref": name, "gateway": gateway, "status": MailboxStatus.ACTIVE,
                "last_checked_at": self._now(),
            }  # fmt: skip
            if connection is not None:
                changes["connection"] = connection
            view = uow.mailboxes.update(existing.id, **changes)
            uow.commit()
        log.info("mailbox_connected", mailbox_id=view.id, gateway=gateway.value)
        return view


def _plain(error: Exception) -> str:
    """A provider error without the provider's prefix: "imap: cannot find..." → "cannot find..."."""
    return str(error).split(": ", 1)[-1]


def pending_workspace(identity: IdentityUnitOfWorkFactory, session_id: str) -> str | None:
    """The workspace a mailbox sign-in was started from, for the page the provider returns to
    (one address for every workspace, so it cannot say which)."""
    with identity() as ids:
        pending = ids.sessions.data(session_id).get("oauth")
    return str(pending["workspace_id"]) if isinstance(pending, dict) else None
