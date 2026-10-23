"""A Microsoft 365 or Outlook mailbox through Microsoft Graph (Phase 6c).

The only way into Microsoft 365 for a new app: basic-auth IMAP is gone and SMTP basic auth is
being switched off. Signs in with OAuth (``outbound.providers.oauth``); the token comes from an
``AccessTokens`` source that keeps it fresh, and a 401 gets one renewal and one more try.

Our drafts are tagged with a single-value extended property that holds our Message-ID, because
that is what a filter can find reliably; ``internetMessageId`` is set as well, so the sent
message carries it. Bodies are read as plain text (``Prefer: outlook.body-content-type``).

Docs: https://learn.microsoft.com/graph/api/user-post-messages ,
``.../singlevaluelegacyextendedproperty-get``, ``.../user-list-messages``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import httpx

from outbound.providers.errors import ProviderAuthError, ProviderError
from outbound.providers.http import HttpClient
from outbound.providers.ports import AccessTokens, InboundMessage, OutgoingDraft, SentMessage

BASE_URL = "https://graph.microsoft.com/v1.0"
# Our own property set (any fixed GUID): "String {GUID} Name OutboundMessageId".
TAG = "String {6f2b8a51-3c0e-4d7a-9b1f-2e8c5d4a7b90} Name OutboundMessageId"
TEXT_BODIES = {"Prefer": 'outlook.body-content-type="text"'}
PAGE = 100
MAX_MESSAGES = 500


def _odata(value: str) -> str:
    return value.replace("'", "''")


def _when(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_when(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _address(entry: object) -> str:
    if isinstance(entry, dict):
        inner = entry.get("emailAddress") or {}
        return str(inner.get("address") or "").lower()
    return ""


class GraphMailbox:
    name = "graph"

    def __init__(
        self, address: str, tokens: AccessTokens, *, client: httpx.Client | None = None
    ) -> None:
        self.address = address
        self._tokens = tokens
        self._http = HttpClient(self.name, BASE_URL, client=client)

    # ------------------------------------------------------------------ the port

    def append_draft(self, draft: OutgoingDraft) -> str:
        if not draft.message_id:
            raise ProviderError(self.name, "a draft needs our Message-ID to be found again")
        self._call(
            "POST",
            "/me/messages",
            json={
                "subject": draft.subject,
                "body": {"contentType": "Text", "content": draft.body},
                "toRecipients": [{"emailAddress": {"address": draft.to_address}}],
                "internetMessageId": draft.message_id,
                "singleValueExtendedProperties": [{"id": TAG, "value": draft.message_id}],
            },
        )
        return draft.message_id

    def draft_exists(self, remote_draft_id: str) -> bool:
        return bool(self._tagged(remote_draft_id))

    def delete_draft(self, remote_draft_id: str) -> int:
        found = self._tagged(remote_draft_id)
        for graph_id in found:
            self._call("DELETE", f"/me/messages/{graph_id}")
        return len(found)

    def list_sent(self, since: datetime) -> list[SentMessage]:
        sent = []
        for item in self._messages(
            "sentitems",
            "sentDateTime",
            since,
            "internetMessageId,toRecipients,subject,sentDateTime,body",
        ):
            when = _parse_when(item.get("sentDateTime"))
            ident = item.get("internetMessageId")
            if when is None or not ident:
                continue
            recipients = item.get("toRecipients") or []
            sent.append(
                SentMessage(
                    rfc_message_id=str(ident),
                    to_address=_address(recipients[0]) if recipients else "",
                    subject=str(item.get("subject") or ""),
                    sent_at=when,
                    body=str((item.get("body") or {}).get("content") or "").strip(),
                )
            )
        return sent

    def list_inbox(self, since: datetime) -> list[InboundMessage]:
        received = []
        fields = "internetMessageId,from,subject,receivedDateTime,body,internetMessageHeaders"
        for item in self._messages("inbox", "receivedDateTime", since, fields):
            when = _parse_when(item.get("receivedDateTime"))
            ident = item.get("internetMessageId")
            if when is None or not ident:
                continue
            headers = {
                str(h.get("name", "")).lower(): str(h.get("value", ""))
                for h in item.get("internetMessageHeaders") or []
            }
            received.append(
                InboundMessage(
                    rfc_message_id=str(ident),
                    from_address=_address(item.get("from")),
                    subject=str(item.get("subject") or ""),
                    received_at=when,
                    body=str((item.get("body") or {}).get("content") or "").strip(),
                    in_reply_to=headers.get("in-reply-to") or None,
                    references=headers.get("references") or None,
                )
            )
        return received

    # ------------------------------------------------------------------ plumbing

    def _tagged(self, message_id: str) -> list[str]:
        """Graph ids of drafts carrying our tag with this Message-ID."""
        flt = (
            f"singleValueExtendedProperties/Any(ep: ep/id eq '{_odata(TAG)}' "
            f"and ep/value eq '{_odata(message_id)}')"
        )
        answer = self._call(
            "GET", "/me/mailFolders/drafts/messages", params={"$filter": flt, "$select": "id"}
        )
        return [str(m["id"]) for m in (answer or {}).get("value", []) if m.get("id")]

    def _messages(
        self, folder: str, field: str, since: datetime, select: str
    ) -> Iterator[dict[str, Any]]:
        """A folder's messages since a time, newest first, page by page."""
        params: dict[str, Any] | None = {
            "$filter": f"{field} ge {_when(since)}",
            "$orderby": f"{field} desc",
            "$select": select,
            "$top": PAGE,
        }
        path: str | None = f"/me/mailFolders/{folder}/messages"
        seen = 0
        while path and seen < MAX_MESSAGES:
            answer = self._call("GET", path, params=params, headers=TEXT_BODIES) or {}
            for item in answer.get("value", []):
                seen += 1
                yield item
            link = answer.get("@odata.nextLink")
            path, params = (str(link) if link else None), None  # the link carries the query

    def _call(
        self, method: str, path: str, *, headers: dict[str, str] | None = None, **kwargs: Any
    ) -> Any:
        try:
            return self._http.request(
                method,
                path,
                headers={**(headers or {}), **self._auth(self._tokens.current())},
                **kwargs,
            )
        except ProviderAuthError as error:
            if error.status_code != 401:
                raise
            # The token was refused before it should have expired: renew once and try again.
            return self._http.request(
                method,
                path,
                headers={**(headers or {}), **self._auth(self._tokens.renew())},
                **kwargs,
            )

    @staticmethod
    def _auth(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}
