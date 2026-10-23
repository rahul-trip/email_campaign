"""In-memory Microsoft Graph and Gmail API servers for the mailbox adapters, built from the
request and response shapes in each vendor's documentation (no live recordings)."""

from __future__ import annotations

import base64
import itertools
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email import message_from_bytes
from email.message import EmailMessage
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx


@dataclass
class FakeTokens:
    """An ``AccessTokens`` source: ``renew`` hands out the next token."""

    token: str = "at-1"
    renewals: int = 0

    def current(self) -> str:
        return self.token

    def renew(self) -> str:
        self.renewals += 1
        self.token = f"at-{self.renewals + 1}"
        return self.token


def _unauthorized(request: httpx.Request, valid: set[str]) -> httpx.Response | None:
    if request.headers.get("authorization", "").removeprefix("Bearer ") not in valid:
        return httpx.Response(401, json={"error": {"code": "InvalidAuthenticationToken"}})
    return None


# ------------------------------------------------------------------ Microsoft Graph


@dataclass
class FakeGraph:
    valid_tokens: set[str] = field(default_factory=lambda: {"at-1"})
    messages: list[dict[str, Any]] = field(default_factory=list)
    page_size_cap: int = 2  # small, so paging through @odata.nextLink is exercised
    _ids: Any = field(default_factory=lambda: itertools.count(1))

    def put_sent(
        self, *, message_id: str, to: str, subject: str, sent_at: datetime, body: str
    ) -> None:
        self.messages.append(
            {
                "id": f"AAMk{next(self._ids)}", "folder": "sentitems",
                "internetMessageId": message_id,
                "subject": subject, "toRecipients": [{"emailAddress": {"address": to}}],
                "sentDateTime": sent_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "body": {"contentType": "text", "content": body},
            }
        )  # fmt: skip

    def __call__(self, request: httpx.Request) -> httpx.Response:
        refused = _unauthorized(request, self.valid_tokens)
        if refused:
            return refused
        url = urlsplit(str(request.url))
        path = url.path.removeprefix("/v1.0")
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        if request.method == "POST" and path == "/me/messages":
            body = json.loads(request.content)
            created = {**body, "id": f"AAMk{next(self._ids)}", "folder": "drafts", "isDraft": True}
            self.messages.append(created)
            return httpx.Response(201, json=created)
        if request.method == "DELETE" and path.startswith("/me/messages/"):
            graph_id = path.rsplit("/", 1)[1]
            before = len(self.messages)
            self.messages = [m for m in self.messages if m["id"] != graph_id]
            return httpx.Response(204 if len(self.messages) < before else 404)
        folder = re.fullmatch(r"/me/mailFolders/(\w+)/messages", path)
        if request.method == "GET" and folder:
            return self._list(folder.group(1), query, request)
        return httpx.Response(400, json={"error": {"code": "BadRequest"}})

    def _list(self, folder: str, query: dict[str, str], request: httpx.Request) -> httpx.Response:
        items = [m for m in self.messages if m["folder"] == folder]
        flt = query.get("$filter", "")
        tagged = re.search(r"ep/value eq '((?:[^']|'')*)'\)$", flt)
        if tagged:
            wanted = tagged.group(1).replace("''", "'")
            items = [
                m for m in items
                if any(p["value"] == wanted for p in m.get("singleValueExtendedProperties", []))
            ]  # fmt: skip
        since = re.search(r"(sentDateTime|receivedDateTime) ge (\S+)", flt)
        if since:
            field_name, moment = since.groups()
            items = [m for m in items if m.get(field_name, "") >= moment]
            items.sort(key=lambda m: m[field_name], reverse=True)
            assert request.headers.get("prefer") == 'outlook.body-content-type="text"'
        skip = int(query.get("$skip", "0"))
        top = min(int(query.get("$top", "10")), self.page_size_cap)
        page = items[skip : skip + top]
        answer: dict[str, Any] = {"value": page}
        if skip + top < len(items):
            next_query = dict(query, **{"$skip": str(skip + top)})
            answer["@odata.nextLink"] = str(
                request.url.copy_with(
                    query="&".join(f"{k}={v}" for k, v in next_query.items()).encode()
                )
            )
        return httpx.Response(200, json=answer)


# ------------------------------------------------------------------ Gmail API


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@dataclass
class FakeGmail:
    valid_tokens: set[str] = field(default_factory=lambda: {"at-1"})
    drafts: list[dict[str, Any]] = field(default_factory=list)  # {"id", "raw" bytes}
    sent: list[dict[str, Any]] = field(default_factory=list)  # {"id", "raw", "internalDate" s}
    page_size_cap: int = 2
    _ids: Any = field(default_factory=lambda: itertools.count(1))

    def put_sent(
        self, *, message_id: str, to: str, subject: str, sent_at: datetime, body: str
    ) -> None:
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = "sam@quantra.example", to, subject
        message["Date"] = sent_at.strftime("%a, %d %b %Y %H:%M:%S +0000")
        message["Message-ID"] = message_id
        message.set_content(body)
        self.sent.append(
            {
                "id": f"18c{next(self._ids)}",
                "raw": message.as_bytes(),
                "at": int(sent_at.timestamp()),
            }
        )

    def __call__(self, request: httpx.Request) -> httpx.Response:
        refused = _unauthorized(request, self.valid_tokens)
        if refused:
            return refused
        url = urlsplit(str(request.url))
        path = url.path.removeprefix("/gmail/v1/users/me")
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        if request.method == "POST" and path == "/drafts":
            raw = json.loads(request.content)["message"]["raw"]
            draft = {"id": f"r-{next(self._ids)}", "raw": base64.urlsafe_b64decode(raw + "==")}
            self.drafts.append(draft)
            return httpx.Response(
                200, json={"id": draft["id"], "message": {"id": "m1", "threadId": "t1"}}
            )
        if request.method == "GET" and path == "/drafts":
            wanted = query.get("q", "").removeprefix("rfc822msgid:")
            hits = [
                d
                for d in self.drafts
                if message_from_bytes(d["raw"])["Message-ID"].strip("<>") == wanted
            ]
            return httpx.Response(
                200, json={"drafts": [{"id": d["id"]} for d in hits]} if hits else {}
            )
        if request.method == "DELETE" and path.startswith("/drafts/"):
            draft_id = path.rsplit("/", 1)[1]
            self.drafts = [d for d in self.drafts if d["id"] != draft_id]
            return httpx.Response(204)
        if request.method == "GET" and path == "/messages":
            q = query.get("q", "")
            assert q.startswith("in:sent ") or q.startswith("in:inbox ")
            after = int(re.search(r"after:(\d+)", q).group(1))  # type: ignore[union-attr]
            pool = self.sent if q.startswith("in:sent") else []
            hits = [m for m in pool if m["at"] >= after - 86_400]  # Gmail is loose by a day
            start = int(query.get("pageToken", "0"))
            size = min(int(query.get("maxResults", "100")), self.page_size_cap)
            answer: dict[str, Any] = {
                "messages": [{"id": m["id"], "threadId": "t"} for m in hits[start : start + size]]
            }
            if start + size < len(hits):
                answer["nextPageToken"] = str(start + size)
            return httpx.Response(200, json=answer if hits else {"resultSizeEstimate": 0})
        found = re.fullmatch(r"/messages/(\w+)", path)
        if request.method == "GET" and found:
            assert query.get("format") == "raw"
            message = next(m for m in self.sent if m["id"] == found.group(1))
            return httpx.Response(200, json={"id": message["id"], "raw": _b64(message["raw"])})
        return httpx.Response(400, json={"error": {"code": 400}})
