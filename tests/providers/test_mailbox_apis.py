"""The Microsoft Graph and Gmail mailboxes (Phase 6c): the shared contract against fake servers
built from each vendor's documentation, and what happens when a token is refused."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from outbound.providers.adapters.gmail_api import GmailMailbox
from outbound.providers.adapters.ms_graph import TAG, GraphMailbox
from outbound.providers.errors import ProviderAuthError
from tests.contract.mailbox_contract import MailboxContract, World, draft
from tests.providers.helpers import mock_client
from tests.providers.mail_fakes import FakeGmail, FakeGraph, FakeTokens

ADDRESS = "sam@quantra.example"


class TestGraphMailboxContract(MailboxContract):
    def world(self) -> World:
        server = FakeGraph()
        return World(
            GraphMailbox(ADDRESS, FakeTokens(), client=mock_client(server)), server.put_sent
        )


class TestGmailMailboxContract(MailboxContract):
    def world(self) -> World:
        server = FakeGmail()
        return World(
            GmailMailbox(ADDRESS, FakeTokens(), client=mock_client(server)), server.put_sent
        )


def test_a_graph_draft_carries_our_tag_and_message_id() -> None:
    server = FakeGraph()
    GraphMailbox(ADDRESS, FakeTokens(), client=mock_client(server)).append_draft(draft(7))
    [saved] = server.messages
    assert saved["internetMessageId"] == "<draft-7.outbound@quantra.example>"
    assert saved["singleValueExtendedProperties"] == [
        {"id": TAG, "value": "<draft-7.outbound@quantra.example>"}
    ]
    assert saved["toRecipients"] == [{"emailAddress": {"address": "jane@acme.com"}}]
    assert saved["body"] == {"contentType": "Text", "content": "Hello Jane, note 7."}


def test_a_gmail_draft_is_our_own_rfc822_message() -> None:
    server = FakeGmail()
    GmailMailbox(ADDRESS, FakeTokens(), from_name="Sam", client=mock_client(server)).append_draft(
        draft(3)
    )
    [saved] = server.drafts
    text = saved["raw"].decode()
    assert "Message-ID: <draft-3.outbound@quantra.example>" in text
    assert "From: Sam <sam@quantra.example>" in text and "To: jane@acme.com" in text


@pytest.mark.parametrize("kind", ["graph", "gmail"])
def test_a_refused_token_is_renewed_once_and_the_call_goes_through(kind: str) -> None:
    server = (
        FakeGraph(valid_tokens={"at-2"}) if kind == "graph" else FakeGmail(valid_tokens={"at-2"})
    )
    tokens = FakeTokens()
    box = (GraphMailbox if kind == "graph" else GmailMailbox)(
        ADDRESS, tokens, client=mock_client(server)
    )
    assert box.draft_exists("<nothing@x>") is False
    assert tokens.renewals == 1


@pytest.mark.parametrize("kind", ["graph", "gmail"])
def test_a_token_refused_after_renewal_is_an_auth_error(kind: str) -> None:
    server = FakeGraph(valid_tokens=set()) if kind == "graph" else FakeGmail(valid_tokens=set())
    box = (GraphMailbox if kind == "graph" else GmailMailbox)(
        ADDRESS, FakeTokens(), client=mock_client(server)
    )
    with pytest.raises(ProviderAuthError):
        box.draft_exists("<nothing@x>")


def test_graph_follows_next_page_links_on_its_own_host_only() -> None:
    server = FakeGraph()
    for n in range(5):
        server.put_sent(
            message_id=f"<s{n}@x>", to="a@b.com", subject="s",
            sent_at=datetime(2026, 10, 12, 9, n, tzinfo=UTC), body="b",
        )  # fmt: skip
    seen: list[str] = []

    def spy(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        return server(request)

    box = GraphMailbox(ADDRESS, FakeTokens(), client=mock_client(spy))
    assert len(box.list_sent(datetime(2026, 10, 10, tzinfo=UTC))) == 5
    assert set(seen) == {"graph.microsoft.com"} and len(seen) == 3


def test_gmail_reads_every_page_of_sent_mail() -> None:
    server = FakeGmail()
    for n in range(5):
        server.put_sent(
            message_id=f"<g{n}@x>", to="a@b.com", subject="s",
            sent_at=datetime(2026, 10, 12, 9, n, tzinfo=UTC), body="b",
        )  # fmt: skip
    box = GmailMailbox(ADDRESS, FakeTokens(), client=mock_client(server))
    sent = box.list_sent(datetime(2026, 10, 10, tzinfo=UTC))
    assert [s.rfc_message_id for s in sent] == [f"<g{n}@x>" for n in range(4, -1, -1)]


def test_no_draft_body_or_token_reaches_an_error_message() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error": {"message": json.loads(request.content or b"{}").get("subject")}}
        )

    box = GraphMailbox(ADDRESS, FakeTokens(), client=mock_client(broken))
    with pytest.raises(Exception) as caught:
        box.append_draft(draft(1))
    assert "Hello Jane" not in str(caught.value) and "at-1" not in str(caught.value)
