"""Building and reading email messages (RFC 5322), shared by every mailbox adapter.

IMAP stores the bytes as they are; the Gmail API takes and returns the same bytes in base64;
Microsoft Graph is given fields but reads back the same headers. So drafts are built here once,
and sent or received messages become the port's models here once.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from email import message_from_bytes, policy
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid, parseaddr, parsedate_to_datetime
from typing import Any

from outbound.providers.ports import InboundMessage, OutgoingDraft, SentMessage


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


def parse(raw: bytes) -> EmailMessage | None:
    parsed = message_from_bytes(raw, policy=policy.default)
    return parsed if isinstance(parsed, EmailMessage) else None


def sent_message(message: EmailMessage) -> SentMessage | None:
    """A message from the Sent folder, or None if it has no Message-ID or date."""
    ident, when = message["Message-ID"], date_of(message)
    if ident is None or when is None:
        return None
    return SentMessage(
        rfc_message_id=str(ident).strip(),
        to_address=first_address(message["To"]),
        subject=str(message["Subject"] or ""),
        sent_at=when,
        body=text_of(message),
    )


def inbound_message(message: EmailMessage) -> InboundMessage | None:
    """A received message, or None if it has no Message-ID or date."""
    ident, when = message["Message-ID"], date_of(message)
    if ident is None or when is None:
        return None
    return InboundMessage(
        rfc_message_id=str(ident).strip(),
        from_address=first_address(message["From"]),
        subject=str(message["Subject"] or ""),
        received_at=when,
        body=text_of(message),
        in_reply_to=header(message, "In-Reply-To"),
        references=header(message, "References"),
    )


def date_of(message: Any) -> datetime | None:
    value = message["Date"]
    if value is None:
        return None
    try:
        parsed = parsedate_to_datetime(str(value))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def first_address(header: object) -> str:
    return parseaddr(str(header or ""))[1].lower()


def header(message: Any, name: str) -> str | None:
    value = message[name]
    return str(value).strip() or None if value is not None else None


_BLANK_RUNS = re.compile(r"\n{3,}")


def text_of(message: EmailMessage) -> str:
    part = message.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    text = part.get_content()
    return _BLANK_RUNS.sub("\n\n", str(text)).strip()
