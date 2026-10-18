"""A mailbox over plain IMAP: save drafts, delete them, and read the Sent and Inbox folders.

Works with any IMAP server (Hostinger today) because it uses only standard commands. Each
operation opens its own short session and logs out, which suits a scheduler that runs a pass
and exits, and avoids a stale connection that a long-lived object would have to detect.

Ported from the legacy ``agent/tools/mailer`` (``drafts/imap_provider.py`` and
``core/message_builder.py``). Moving to an OAuth-only provider means another class behind the
same ``Mailbox`` port.
"""

from __future__ import annotations

import imaplib
import re
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from email import message_from_bytes, policy
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid, parseaddr, parsedate_to_datetime
from typing import Any

from outbound.providers.errors import ProviderAuthError, ProviderError
from outbound.providers.ports import InboundMessage, OutgoingDraft, SentMessage

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
MAX_MESSAGES_PER_LIST = 500  # newest first; a tick that sees more than this has been off too long


def imap_date(moment: datetime) -> str:
    """``17-Oct-2026``. Built by hand because ``strftime`` follows the machine's locale."""
    day = moment.astimezone(UTC)
    return f"{day.day:02d}-{_MONTHS[day.month - 1]}-{day.year}"


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_message(
    draft: OutgoingDraft, *, from_address: str, from_name: str = "", now: datetime | None = None
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = (
        str(Address(display_name=from_name, addr_spec=from_address)) if from_name else from_address
    )
    message["To"] = draft.to_address
    message["Subject"] = draft.subject
    message["Date"] = format_datetime(now or datetime.now(UTC))
    message["Message-ID"] = draft.message_id or make_msgid(
        domain=from_address.rpartition("@")[2] or None
    )
    if draft.in_reply_to:
        message["In-Reply-To"] = draft.in_reply_to
        message["References"] = draft.references or draft.in_reply_to
    message.set_content(draft.body)
    return message


class ImapMailbox:
    def __init__(
        self,
        *,
        host: str,
        address: str,
        password: str,
        port: int = 993,
        use_ssl: bool = True,
        from_name: str = "",
        drafts_folder: str = "Drafts",
        sent_folder: str = "Sent",
        inbox_folder: str = "INBOX",
        timeout: float = 30.0,
        connect: Callable[[], imaplib.IMAP4] | None = None,
    ) -> None:
        if not host or not address or not password:
            raise ProviderAuthError(
                "imap", "IMAP_HOST, EMAIL_ADDRESS and EMAIL_PASSWORD are needed"
            )
        self.address = address
        self._password = password
        self._from_name = from_name
        self._drafts = drafts_folder
        self._sent = sent_folder
        self._inbox = inbox_folder
        if connect is not None:
            self._connect = connect
        elif use_ssl:
            self._connect = lambda: imaplib.IMAP4_SSL(host, port, timeout=timeout)
        else:
            self._connect = lambda: imaplib.IMAP4(host, port, timeout=timeout)

    # ------------------------------------------------------------------ the port

    def append_draft(self, draft: OutgoingDraft) -> str:
        message = build_message(draft, from_address=self.address, from_name=self._from_name)
        with self._session() as conn:
            status, response = conn.append(
                _quote(self._drafts) if " " in self._drafts else self._drafts,
                r"(\Draft)",
                imaplib.Time2Internaldate(time.time()),
                message.as_bytes(),
            )
            if status != "OK":
                raise ProviderError("imap", f"APPEND to {self._drafts} failed: {response!r}")
        return str(message["Message-ID"])

    def draft_exists(self, remote_draft_id: str) -> bool:
        with self._session() as conn:
            self._select(conn, self._drafts, readonly=True)
            return bool(self._search(conn, "HEADER", "Message-ID", _quote(remote_draft_id)))

    def delete_draft(self, remote_draft_id: str) -> int:
        with self._session() as conn:
            self._select(conn, self._drafts, readonly=False)
            found = self._search(conn, "HEADER", "Message-ID", _quote(remote_draft_id))
            for number in found:
                conn.store(number, "+FLAGS", r"(\Deleted)")
            if found:
                conn.expunge()
            return len(found)

    def list_sent(self, since: datetime) -> list[SentMessage]:
        sent: list[SentMessage] = []
        for message in self._read(self._sent, since):
            ident = message["Message-ID"]
            when = _date_of(message)
            if ident is None or when is None:
                continue
            sent.append(
                SentMessage(
                    rfc_message_id=str(ident).strip(),
                    to_address=_first_address(message["To"]),
                    subject=str(message["Subject"] or ""),
                    sent_at=when,
                    body=_text_of(message),
                )
            )
        return sent

    def list_inbox(self, since: datetime) -> list[InboundMessage]:
        received: list[InboundMessage] = []
        for message in self._read(self._inbox, since):
            ident = message["Message-ID"]
            when = _date_of(message)
            if ident is None or when is None:
                continue
            received.append(
                InboundMessage(
                    rfc_message_id=str(ident).strip(),
                    from_address=_first_address(message["From"]),
                    subject=str(message["Subject"] or ""),
                    received_at=when,
                    body=_text_of(message),
                    in_reply_to=_header(message, "In-Reply-To"),
                    references=_header(message, "References"),
                )
            )
        return received

    # ------------------------------------------------------------------ plumbing

    @contextmanager
    def _session(self) -> Iterator[imaplib.IMAP4]:
        try:
            conn = self._connect()
        except (OSError, imaplib.IMAP4.error) as exc:
            raise ProviderError(
                "imap", f"cannot connect: {type(exc).__name__}", retryable=True
            ) from None
        try:
            try:
                conn.login(self.address, self._password)
            except imaplib.IMAP4.error:
                raise ProviderAuthError("imap", "the server rejected the login") from None
            yield conn
        except (OSError, imaplib.IMAP4.error) as exc:
            raise ProviderError(
                "imap", f"{type(exc).__name__} during session", retryable=True
            ) from None
        finally:
            with suppress(OSError, imaplib.IMAP4.error):
                conn.logout()

    def _select(self, conn: imaplib.IMAP4, folder: str, *, readonly: bool) -> None:
        status, response = conn.select(_quote(folder) if " " in folder else folder, readonly)
        if status != "OK":
            raise ProviderError("imap", f"cannot open folder {folder!r}: {response!r}")

    @staticmethod
    def _search(conn: imaplib.IMAP4, *criteria: str) -> list[str]:
        status, data = conn.search(None, *criteria)
        if status != "OK":
            raise ProviderError("imap", f"SEARCH failed: {data!r}")
        first = data[0] if data else None
        return first.decode("ascii").split() if isinstance(first, bytes) else []

    def _read(self, folder: str, since: datetime) -> list[EmailMessage]:
        """Messages in ``folder`` dated at or after ``since``, newest first."""
        cutoff = since.astimezone(UTC)
        messages: list[EmailMessage] = []
        with self._session() as conn:
            self._select(conn, folder, readonly=True)
            numbers = self._search(conn, "SINCE", imap_date(cutoff))
            for number in reversed(numbers[-MAX_MESSAGES_PER_LIST:]):
                status, data = conn.fetch(number, "(BODY.PEEK[])")
                raw = _raw_bytes(data) if status == "OK" else None
                if raw is None:
                    continue
                parsed = message_from_bytes(raw, policy=policy.default)
                when = _date_of(parsed)  # SINCE has day granularity, so filter exactly here
                if isinstance(parsed, EmailMessage) and when is not None and when >= cutoff:
                    messages.append(parsed)
        return messages


def _raw_bytes(data: Any) -> bytes | None:
    for part in data or []:
        if isinstance(part, tuple) and len(part) > 1 and isinstance(part[1], bytes):
            return part[1]
    return None


def _date_of(message: Any) -> datetime | None:
    value = message["Date"]
    if value is None:
        return None
    try:
        parsed = parsedate_to_datetime(str(value))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _first_address(header: object) -> str:
    return parseaddr(str(header or ""))[1].lower()


def _header(message: Any, name: str) -> str | None:
    value = message[name]
    return str(value).strip() or None if value is not None else None


_BLANK_RUNS = re.compile(r"\n{3,}")


def _text_of(message: EmailMessage) -> str:
    part = message.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    text = part.get_content()
    return _BLANK_RUNS.sub("\n\n", str(text)).strip()
