"""The IMAP mailbox against an in-memory server: drafts, deletion, Sent and Inbox reading."""

from __future__ import annotations

import imaplib
from datetime import UTC, datetime
from email import message_from_bytes, policy
from email.message import EmailMessage
from typing import Any

import pytest

from outbound.providers.adapters.imap_mailbox import ImapMailbox, build_message, imap_date
from outbound.providers.errors import ProviderAuthError, ProviderError
from outbound.providers.ports import OutgoingDraft
from tests.contract.mailbox_contract import MailboxContract, World

ADDRESS = "sales@quantra.example"
PASSWORD = "p4ss-secret"
SINCE = datetime(2026, 10, 10, tzinfo=UTC)


def raw_mail(
    *,
    message_id: str,
    to: str = "jane@acme.com",
    sender: str = ADDRESS,
    subject: str = "grid demand",
    date: str = "Mon, 12 Oct 2026 09:30:00 +0000",
    body: str = "Hello Jane",
    extra: dict[str, str] | None = None,
) -> bytes:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    message["Date"] = date
    message["Message-ID"] = message_id
    for name, value in (extra or {}).items():
        message[name] = value
    message.set_content(body)
    return message.as_bytes()


class FakeImap:
    """Just enough of imaplib for the adapter: folders of raw messages, numbered from 1, each
    with a UID that never changes and its flags. ``special_use`` marks folders the way a server
    announces them in LIST (``{"INBOX.Brouillons": "\\\\Drafts"}``)."""

    def __init__(
        self,
        folders: dict[str, list[bytes]],
        password: str = PASSWORD,
        *,
        uidplus: bool = True,
        special_use: dict[str, str] | None = None,
    ) -> None:
        self.folders = folders
        self._password = password
        self._caps = "IMAP4rev1 UIDPLUS" if uidplus else "IMAP4rev1"
        self.special_use = special_use or {}
        self.selected: str | None = None
        self.logged_out = False
        self.flags_on_append: list[str] = []
        self.plain_expunges = 0
        self._rows: dict[str, list[tuple[int, set[str]]]] = {}
        self._next_uid = 100

    # bookkeeping: messages a test appended straight to ``folders`` get a UID on first sight
    def rows(self, folder: str) -> list[tuple[int, set[str]]]:
        rows = self._rows.setdefault(folder, [])
        while len(rows) < len(self.folders[folder]):
            self._next_uid += 1
            rows.append((self._next_uid, set()))
        return rows

    def flag(self, folder: str, index: int, flag: str) -> None:
        self.rows(folder)[index][1].add(flag)

    def _drop(self, keep: Any) -> None:
        assert self.selected is not None
        rows, messages = self.rows(self.selected), self.folders[self.selected]
        kept = [(row, raw) for row, raw in zip(rows, messages, strict=True) if keep(row)]
        self._rows[self.selected] = [row for row, _ in kept]
        self.folders[self.selected] = [raw for _, raw in kept]

    def _matching(self, criteria: tuple[str, ...]) -> list[int]:
        assert self.selected is not None
        messages = self.folders[self.selected]
        if criteria[0] == "HEADER":
            wanted = criteria[2].strip('"')
            return [
                i
                for i, raw in enumerate(messages)
                if message_from_bytes(raw)["Message-ID"] == wanted
            ]
        return list(range(len(messages)))  # the server's day filter is loose

    # imaplib
    def login(self, user: str, password: str) -> tuple[str, list[bytes]]:
        if password != self._password:
            raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] nope")
        return "OK", [b"logged in"]

    def logout(self) -> tuple[str, list[bytes]]:
        self.logged_out = True
        return "BYE", []

    def capability(self) -> tuple[str, list[bytes]]:
        return "OK", [self._caps.encode()]

    def folder_list(self) -> tuple[str, list[bytes]]:
        lines = []
        for name in self.folders:
            flags = "\\HasNoChildren" + (
                f" {self.special_use[name]}" if name in self.special_use else ""
            )
            lines.append(f'({flags}) "/" "{name}"'.encode())
        return "OK", lines

    def select(self, folder: str, readonly: bool = False) -> tuple[str, list[bytes]]:
        name = folder.strip('"')
        if name not in self.folders:
            return "NO", [b"no such folder"]
        self.selected = name
        return "OK", [b"1"]

    def append(self, folder: str, flags: str, date: Any, message: bytes) -> tuple[str, list[bytes]]:
        name = folder.strip('"')
        if name not in self.folders:
            return "NO", [b"[TRYCREATE]"]
        self.flags_on_append.append(flags)
        self.folders[name].append(message)
        return "OK", [b"done"]

    def search(self, charset: None, *criteria: str) -> tuple[str, list[bytes]]:
        return "OK", [" ".join(str(i + 1) for i in self._matching(criteria)).encode()]

    def uid(self, command: str, *args: str) -> tuple[str, list[bytes]]:
        assert self.selected is not None
        rows = self.rows(self.selected)
        if command == "SEARCH":
            return "OK", [" ".join(str(rows[i][0]) for i in self._matching(args)).encode()]
        if command == "STORE":
            uids = {int(u) for u in args[0].split(",")}
            for uid, flags in rows:
                if uid in uids:
                    flags.add("\\Deleted")
            return "OK", []
        raise AssertionError(f"unexpected UID {command}")

    def _simple_command(self, name: str, *args: str) -> tuple[str, list[bytes]]:
        assert (name, args[0]) == ("UID", "EXPUNGE"), (name, args)
        uids = {int(u) for u in args[1].split(",")}
        self._drop(lambda row: not (row[0] in uids and "\\Deleted" in row[1]))
        return "OK", []

    def fetch(self, number: str, spec: str) -> tuple[str, list[Any]]:
        assert self.selected is not None
        raw = self.folders[self.selected][int(number) - 1]
        return "OK", [(b"1 (BODY[] {%d}" % len(raw), raw), b")"]

    def expunge(self) -> tuple[str, list[bytes]]:
        self.plain_expunges += 1
        self._drop(lambda row: "\\Deleted" not in row[1])
        return "OK", []


# imaplib's LIST is ``list()``; defined under another name so it does not hide the builtin above.
setattr(FakeImap, "list", FakeImap.folder_list)  # noqa: B010


def mailbox(server: FakeImap, **kwargs: Any) -> ImapMailbox:
    return ImapMailbox(
        host="imap.test",
        address=ADDRESS,
        password=PASSWORD,
        from_name="Sam at Quantra",
        drafts_folder="Drafts",
        sent_folder="Sent",
        connect=lambda: server,  # type: ignore[arg-type,return-value]
        **kwargs,
    )


def fresh() -> FakeImap:
    return FakeImap({"Drafts": [], "Sent": [], "INBOX": []})


# ------------------------------------------------------------------ building messages


def test_a_draft_has_the_headers_a_mail_client_expects() -> None:
    draft = OutgoingDraft(to_address="jane@acme.com", subject="grid demand", body="Hi Jane")
    message = build_message(draft, from_address=ADDRESS, from_name="Sam at Quantra")
    assert message["From"] == f"Sam at Quantra <{ADDRESS}>"
    assert message["To"] == "jane@acme.com"
    assert message["Message-ID"].endswith("@quantra.example>")
    assert message["Date"] is not None
    assert message["In-Reply-To"] is None
    assert message.get_content().strip() == "Hi Jane"


def test_a_follow_up_is_threaded_under_the_previous_message() -> None:
    draft = OutgoingDraft(
        to_address="jane@acme.com", subject="Re: grid demand", body="Nudge", in_reply_to="<a@x>"
    )
    message = build_message(draft, from_address=ADDRESS)
    assert message["In-Reply-To"] == "<a@x>"
    assert message["References"] == "<a@x>"
    assert message["From"] == ADDRESS


def test_imap_dates_do_not_depend_on_the_locale() -> None:
    assert imap_date(datetime(2026, 10, 7, 23, 30, tzinfo=UTC)) == "07-Oct-2026"
    assert imap_date(datetime(2027, 1, 31, tzinfo=UTC)) == "31-Jan-2027"


# ------------------------------------------------------------------ drafts


def test_append_draft_saves_a_draft_flagged_message_and_returns_its_message_id() -> None:
    server = fresh()
    draft_id = mailbox(server).append_draft(
        OutgoingDraft(to_address="jane@acme.com", subject="grid demand", body="Hi Jane")
    )
    assert len(server.folders["Drafts"]) == 1
    saved = message_from_bytes(server.folders["Drafts"][0], policy=policy.default)
    assert saved["Message-ID"] == draft_id
    assert server.flags_on_append == [r"(\Draft)"]
    assert server.logged_out


def test_a_missing_drafts_folder_is_a_clear_error() -> None:
    server = FakeImap({"INBOX": []})
    with pytest.raises(ProviderError, match="APPEND to Drafts failed"):
        mailbox(server).append_draft(
            OutgoingDraft(to_address="jane@acme.com", subject="s", body="b")
        )
    assert server.logged_out


def test_delete_draft_removes_only_the_matching_message() -> None:
    server = fresh()
    box = mailbox(server)
    keep = box.append_draft(OutgoingDraft(to_address="a@x.com", subject="s", body="b"))
    drop = box.append_draft(OutgoingDraft(to_address="b@x.com", subject="s", body="b"))
    assert box.delete_draft(drop) == 1
    remaining = [message_from_bytes(m)["Message-ID"] for m in server.folders["Drafts"]]
    assert remaining == [keep]


def test_deleting_a_draft_that_is_gone_is_not_an_error() -> None:
    assert mailbox(fresh()).delete_draft("<gone@x>") == 0


def test_deleting_our_draft_never_purges_mail_the_person_flagged_for_deletion() -> None:
    """A plain EXPUNGE removes every message flagged \\Deleted in the folder; UID EXPUNGE
    removes only ours."""
    server = fresh()
    box = mailbox(server)
    theirs = box.append_draft(OutgoingDraft(to_address="a@x.com", subject="s", body="b"))
    ours = box.append_draft(OutgoingDraft(to_address="b@x.com", subject="s", body="b"))
    server.flag("Drafts", 0, "\\Deleted")  # they deleted it in their mail program, not purged yet
    assert box.delete_draft(ours) == 1
    remaining = [message_from_bytes(m)["Message-ID"] for m in server.folders["Drafts"]]
    assert remaining == [theirs] and server.plain_expunges == 0


def test_without_uidplus_the_draft_is_only_flagged() -> None:
    server = FakeImap({"Drafts": [], "Sent": [], "INBOX": []}, uidplus=False)
    box = mailbox(server)
    ours = box.append_draft(OutgoingDraft(to_address="b@x.com", subject="s", body="b"))
    assert box.delete_draft(ours) == 1
    assert len(server.folders["Drafts"]) == 1 and server.plain_expunges == 0
    assert "\\Deleted" in server.rows("Drafts")[0][1]


# ------------------------------------------------------------------ finding the folders


def unnamed(server: FakeImap) -> ImapMailbox:
    return ImapMailbox(host="imap.test", address=ADDRESS, password=PASSWORD, connect=lambda: server)  # type: ignore[arg-type,return-value]


def test_folders_marked_with_special_use_are_found_whatever_their_name() -> None:
    server = FakeImap(
        {"INBOX": [], "INBOX.Brouillons": [], "INBOX.Envoyes": []},
        special_use={"INBOX.Brouillons": "\\Drafts", "INBOX.Envoyes": "\\Sent"},
    )
    server.folders["INBOX.Envoyes"].append(raw_mail(message_id="<s@x>"))
    box = unnamed(server)
    box.append_draft(OutgoingDraft(to_address="a@x.com", subject="s", body="b"))
    assert len(server.folders["INBOX.Brouillons"]) == 1
    assert [m.rfc_message_id for m in box.list_sent(SINCE)] == ["<s@x>"]


def test_an_unmarked_server_falls_back_to_common_names() -> None:
    server = FakeImap({"INBOX": [], "INBOX.Drafts": [], "Sent Items": []})
    box = unnamed(server)
    box.append_draft(OutgoingDraft(to_address="a@x.com", subject="s", body="b"))
    assert len(server.folders["INBOX.Drafts"]) == 1
    assert box.list_sent(SINCE) == []


def test_no_drafts_folder_at_all_says_to_name_it() -> None:
    with pytest.raises(ProviderError, match="Drafts folder"):
        unnamed(FakeImap({"INBOX": []})).append_draft(
            OutgoingDraft(to_address="a@x.com", subject="s", body="b")
        )


# ------------------------------------------------------------------ Sent and Inbox


def test_sent_messages_are_read_with_recipient_subject_time_and_text() -> None:
    server = fresh()
    server.folders["Sent"].append(raw_mail(message_id="<s1@quantra.example>", body="Hello Jane\n"))
    [sent] = mailbox(server).list_sent(SINCE)
    assert sent.rfc_message_id == "<s1@quantra.example>"
    assert (sent.to_address, sent.subject) == ("jane@acme.com", "grid demand")
    assert sent.sent_at == datetime(2026, 10, 12, 9, 30, tzinfo=UTC)
    assert sent.body == "Hello Jane"


def test_messages_older_than_since_are_dropped_exactly() -> None:
    server = fresh()
    server.folders["Sent"] += [
        raw_mail(message_id="<old@x>", date="Fri, 09 Oct 2026 23:59:00 +0000"),
        raw_mail(message_id="<new@x>", date="Sat, 10 Oct 2026 00:00:00 +0000"),
    ]
    assert [m.rfc_message_id for m in mailbox(server).list_sent(SINCE)] == ["<new@x>"]


def test_other_time_zones_are_normalised_to_utc() -> None:
    server = fresh()
    server.folders["Sent"].append(
        raw_mail(message_id="<tz@x>", date="Mon, 12 Oct 2026 09:30:00 +0200")
    )
    [sent] = mailbox(server).list_sent(SINCE)
    assert sent.sent_at == datetime(2026, 10, 12, 7, 30, tzinfo=UTC)


def test_messages_missing_an_id_or_a_date_are_skipped() -> None:
    server = fresh()
    no_id = raw_mail(message_id="<x@x>").replace(b"Message-ID: <x@x>\n", b"")
    no_date = raw_mail(message_id="<y@x>").replace(b"Date: Mon, 12 Oct 2026 09:30:00 +0000\n", b"")
    server.folders["Sent"] += [no_id, no_date, raw_mail(message_id="<ok@x>")]
    assert [m.rfc_message_id for m in mailbox(server).list_sent(SINCE)] == ["<ok@x>"]


def test_a_newest_first_order_is_returned() -> None:
    server = fresh()
    server.folders["Sent"] += [raw_mail(message_id=f"<m{i}@x>") for i in range(3)]
    assert [m.rfc_message_id for m in mailbox(server).list_sent(SINCE)] == [
        "<m2@x>",
        "<m1@x>",
        "<m0@x>",
    ]


def test_inbox_messages_carry_threading_headers() -> None:
    server = fresh()
    server.folders["INBOX"].append(
        raw_mail(
            message_id="<r1@acme.com>",
            sender="Jane Doe <Jane@Acme.com>",
            to=ADDRESS,
            subject="Re: grid demand",
            extra={"In-Reply-To": "<s1@quantra.example>", "References": "<s1@quantra.example>"},
        )
    )
    [reply] = mailbox(server).list_inbox(SINCE)
    assert reply.from_address == "jane@acme.com"
    assert reply.in_reply_to == "<s1@quantra.example>"
    assert reply.references == "<s1@quantra.example>"


def test_a_html_only_message_is_still_readable() -> None:
    message = EmailMessage()
    message["From"] = "jane@acme.com"
    message["To"] = ADDRESS
    message["Subject"] = "hi"
    message["Date"] = "Mon, 12 Oct 2026 09:30:00 +0000"
    message["Message-ID"] = "<h@x>"
    message.set_content("<p>Hello</p>", subtype="html")
    server = fresh()
    server.folders["INBOX"].append(message.as_bytes())
    [mail] = mailbox(server).list_inbox(SINCE)
    assert "Hello" in mail.body


# ------------------------------------------------------------------ failures


def test_a_rejected_login_is_an_auth_error_that_hides_the_password() -> None:
    server = FakeImap({"Drafts": []}, password="different")
    with pytest.raises(ProviderAuthError) as caught:
        mailbox(server).list_sent(SINCE)
    assert PASSWORD not in str(caught.value)
    assert server.logged_out


def test_an_unreachable_server_is_a_retryable_error() -> None:
    def refuse() -> imaplib.IMAP4:
        raise ConnectionRefusedError

    box = ImapMailbox(host="h", address=ADDRESS, password=PASSWORD, connect=refuse)
    with pytest.raises(ProviderError) as caught:
        box.list_sent(SINCE)
    assert caught.value.retryable


def test_a_missing_folder_is_an_error_naming_the_folder() -> None:
    server = FakeImap({"Drafts": []})
    with pytest.raises(ProviderError, match="Sent"):
        mailbox(server).list_sent(SINCE)


def test_a_separate_login_name_is_used_when_given() -> None:
    seen: list[str] = []
    server = fresh()
    real_login = server.login

    def login(user: str, password: str) -> tuple[str, list[bytes]]:
        seen.append(user)
        return real_login(user, password)

    server.login = login  # type: ignore[method-assign]
    mailbox(server, username="sam.login").list_sent(SINCE)
    assert seen == ["sam.login"]


def test_missing_credentials_fail_at_construction() -> None:
    with pytest.raises(ProviderAuthError):
        ImapMailbox(host="", address=ADDRESS, password=PASSWORD)
    with pytest.raises(ProviderAuthError):
        ImapMailbox(host="h", address=ADDRESS, password="")


# ------------------------------------------------------------------ idempotent drafts


def test_a_fixed_message_id_is_used_so_saving_can_be_checked_first() -> None:
    server = fresh()
    box = mailbox(server)
    draft = OutgoingDraft(
        to_address="jane@acme.com", subject="s", body="b", message_id="<fixed-1@quantra.example>"
    )
    assert box.draft_exists("<fixed-1@quantra.example>") is False
    assert box.append_draft(draft) == "<fixed-1@quantra.example>"
    assert box.draft_exists("<fixed-1@quantra.example>") is True
    assert box.draft_exists("<other@quantra.example>") is False


def test_a_draft_is_not_looked_for_in_the_wrong_folder() -> None:
    server = fresh()
    server.folders["Sent"].append(raw_mail(message_id="<sent-1@x>"))
    assert mailbox(server).draft_exists("<sent-1@x>") is False


# ------------------------------------------------------------------ the shared contract


class TestImapMailboxContract(MailboxContract):
    def world(self) -> World:
        server = fresh()

        def put_sent(
            *, message_id: str, to: str, subject: str, sent_at: datetime, body: str
        ) -> None:
            date = sent_at.strftime("%a, %d %b %Y %H:%M:%S +0000")
            server.folders["Sent"].append(
                raw_mail(message_id=message_id, to=to, subject=subject, date=date, body=body)
            )

        return World(mailbox(server), put_sent)
