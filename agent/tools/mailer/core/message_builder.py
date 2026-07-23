"""Builds a standard RFC 822 email message, independent of transport/provider."""

from __future__ import annotations

from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import make_msgid


def build_email_message(*, from_addr: str, from_name: str, to_addr: str, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = str(Address(display_name=from_name, addr_spec=from_addr)) if from_name else from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid()
    msg.set_content(body)
    return msg
