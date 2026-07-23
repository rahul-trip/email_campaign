"""IMAP-based draft provider.

Works with any IMAP-compliant mailbox (Hostinger today; Gmail, Outlook, Zoho, or
plain cPanel mail tomorrow) because it only relies on the standard IMAP APPEND
command against the account's Drafts folder — no provider-specific API.

Switching providers later without leaving IMAP is a config change only
(IMAP_HOST / IMAP_PORT / EMAIL_ADDRESS / EMAIL_PASSWORD / DRAFTS_FOLDER in .env).
Switching to a provider that requires OAuth (e.g. Gmail API, Outlook Graph) means
adding a sibling class that implements drafts.base.DraftProvider and pointing
PROVIDER_TYPE at it — ingestion and the campaign runner are untouched either way.
"""

from __future__ import annotations

import imaplib
import logging

from agent.tools.mailer.config.settings import Settings
from agent.tools.mailer.core.message_builder import build_email_message
from agent.tools.mailer.drafts.base import DraftProvider

logger = logging.getLogger(__name__)


class ImapDraftProvider(DraftProvider):
    def __init__(self, settings: Settings):
        self.settings = settings
        self._conn: imaplib.IMAP4 | None = None

    def connect(self) -> None:
        s = self.settings
        if s.imap_use_ssl:
            self._conn = imaplib.IMAP4_SSL(s.imap_host, s.imap_port)
        else:
            self._conn = imaplib.IMAP4(s.imap_host, s.imap_port)
        self._conn.login(s.email_address, s.email_password)
        logger.info("Connected to %s:%s as %s", s.imap_host, s.imap_port, s.email_address)

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.logout()
            except Exception:
                logger.warning("Error while logging out of IMAP session", exc_info=True)
            self._conn = None

    def list_folders(self) -> list[str]:
        """Utility to discover the exact Drafts folder name/path for this mailbox."""
        if self._conn is None:
            raise RuntimeError("Not connected. Call connect() first.")
        status, folders = self._conn.list()
        if status != "OK":
            raise RuntimeError(f"IMAP LIST failed: {status}")
        return [f.decode(errors="replace") if isinstance(f, bytes) else str(f) for f in folders]

    def save_draft(self, *, to_addr: str, subject: str, body: str) -> str:
        if self._conn is None:
            raise RuntimeError("Not connected. Call connect() first.")

        message = build_email_message(
            from_addr=self.settings.email_address,
            from_name=self.settings.from_name,
            to_addr=to_addr,
            subject=subject,
            body=body,
        )

        status, response = self._conn.append(
            self.settings.drafts_folder,
            r"(\Draft)",
            imaplib.Time2Internaldate(__import__("time").time()),
            message.as_bytes(),
        )
        if status != "OK":
            raise RuntimeError(f"IMAP APPEND failed for {to_addr!r}: {response}")

        return f"appended to {self.settings.drafts_folder} ({response!r})"
