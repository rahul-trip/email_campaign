"""A Google Workspace or Gmail mailbox through the Gmail API (Phase 6c).

Scopes ``gmail.compose`` (drafts) and ``gmail.readonly`` (Sent, and later replies). Drafts are
the same RFC 5322 bytes the IMAP adapter builds (``outbound.providers.mime``), sent base64url;
Gmail keeps our Message-ID, so ``rfc822msgid:`` finds the draft again. Sent and received mail
is read as raw bytes and parsed the same way as IMAP's.

Docs: https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.drafts ,
``.../users.messages/list``, ``.../users.messages/get``; search operators:
https://support.google.com/mail/answer/7190
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any

import httpx

from outbound.providers.errors import ProviderAuthError, ProviderError
from outbound.providers.http import HttpClient
from outbound.providers.mime import build_message, inbound_message, parse, sent_message
from outbound.providers.ports import AccessTokens, InboundMessage, OutgoingDraft, SentMessage

BASE_URL = "https://gmail.googleapis.com/gmail/v1/users/me"
PAGE = 100
MAX_MESSAGES = 500


def _search_id(message_id: str) -> str:
    return "rfc822msgid:" + message_id.strip().strip("<>")


class GmailMailbox:
    name = "gmail"

    def __init__(
        self,
        address: str,
        tokens: AccessTokens,
        *,
        from_name: str = "",
        client: httpx.Client | None = None,
    ) -> None:
        self.address = address
        self._tokens = tokens
        self._from_name = from_name
        self._http = HttpClient(self.name, BASE_URL, client=client)

    # ------------------------------------------------------------------ the port

    def append_draft(self, draft: OutgoingDraft) -> str:
        message = build_message(draft, from_address=self.address, from_name=self._from_name)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        self._call("POST", "/drafts", json={"message": {"raw": raw}})
        return str(message["Message-ID"])

    def draft_exists(self, remote_draft_id: str) -> bool:
        return bool(self._drafts(remote_draft_id))

    def delete_draft(self, remote_draft_id: str) -> int:
        found = self._drafts(remote_draft_id)
        for draft_id in found:
            self._call("DELETE", f"/drafts/{draft_id}")
        return len(found)

    def list_sent(self, since: datetime) -> list[SentMessage]:
        return self._read("in:sent", since, sent_message)

    def list_inbox(self, since: datetime) -> list[InboundMessage]:
        return self._read("in:inbox", since, inbound_message)

    # ------------------------------------------------------------------ plumbing

    def _drafts(self, message_id: str) -> list[str]:
        answer = self._call("GET", "/drafts", params={"q": _search_id(message_id)}) or {}
        return [str(d["id"]) for d in answer.get("drafts", []) if d.get("id")]

    def _read[T](self, where: str, since: datetime, convert: Callable[[Any], T | None]) -> list[T]:
        """Messages matching ``where`` since a time, newest first. ``after:`` is a day or an
        epoch second; Gmail's day boundaries are Pacific time, so seconds are used, and each
        message's own date is checked again."""
        found = []
        for gmail_id in self._ids(f"{where} after:{int(since.timestamp())}"):
            answer = self._call("GET", f"/messages/{gmail_id}", params={"format": "raw"}) or {}
            raw = answer.get("raw")
            if not raw:
                continue
            message = parse(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
            item = convert(message) if message is not None else None
            when = getattr(item, "sent_at", None) or getattr(item, "received_at", None)
            if item is not None and when is not None and when >= since:
                found.append((when, item))
        found.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in found]

    def _ids(self, query: str) -> Iterator[str]:
        token: str | None = None
        seen = 0
        while seen < MAX_MESSAGES:
            params: dict[str, Any] = {"q": query, "maxResults": PAGE}
            if token:
                params["pageToken"] = token
            answer = self._call("GET", "/messages", params=params) or {}
            for message in answer.get("messages", []):
                seen += 1
                yield str(message["id"])
            token = answer.get("nextPageToken")
            if not token:
                return

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            return self._http.request(
                method, path, headers=self._auth(self._tokens.current()), **kwargs
            )
        except ProviderAuthError as error:
            if error.status_code != 401:
                raise
            return self._http.request(
                method, path, headers=self._auth(self._tokens.renew()), **kwargs
            )

    @staticmethod
    def _auth(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}


def account_address(access_token: str, *, client: httpx.Client | None = None) -> str:
    """The address of the account a token belongs to, right after connecting."""
    http = HttpClient("gmail", BASE_URL, client=client)
    profile = http.request(
        "GET", "/profile", headers={"Authorization": f"Bearer {access_token}"}
    ) or {}  # fmt: skip
    address = str(profile.get("emailAddress") or "").strip().lower()
    if "@" not in address:
        raise ProviderError("gmail", "the account has no email address")
    return address
