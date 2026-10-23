"""A mailbox over plain IMAP: save drafts, delete them, and read the Sent and Inbox folders.

Works with any IMAP server because it uses only standard commands. Each operation opens its
own short session and logs out, which suits a scheduler that runs a pass and exits, and avoids
a stale connection that a long-lived object would have to detect.

The host is typed in by a customer (Phase 6c), so the connection is guarded
(``outbound.providers.netguard``): only public addresses, only ports 993 (TLS) and 143
(STARTTLS, required), and the socket goes to the address that was checked. Drafts are deleted
by UID with ``UID EXPUNGE``, so other messages flagged for deletion in the folder are never
purged with them. The Drafts and Sent folders are found through SPECIAL-USE when not given.

Ported from the legacy ``agent/tools/mailer`` (``drafts/imap_provider.py`` and
``core/message_builder.py``).
"""

from __future__ import annotations

import imaplib
import re
import socket
import ssl
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any

from outbound.logging import get_logger
from outbound.providers.errors import ProviderAuthError, ProviderError
from outbound.providers.mime import build_message, date_of, inbound_message, parse, sent_message
from outbound.providers.netguard import Resolve, public_address, system_resolve
from outbound.providers.ports import InboundMessage, OutgoingDraft, SentMessage

__all__ = ["ImapMailbox", "build_message", "guarded_connect", "imap_date"]

log = get_logger(__name__)

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
MAX_MESSAGES_PER_LIST = 500  # newest first; a tick that sees more than this has been off too long
TLS_PORT, STARTTLS_PORT = 993, 143
# Common names, tried when the server does not mark its folders (SPECIAL-USE, RFC 6154).
DRAFTS_NAMES = ("Drafts", "INBOX.Drafts", "Draft", "[Gmail]/Drafts")
SENT_NAMES = ("Sent", "INBOX.Sent", "Sent Items", "Sent Messages", "[Gmail]/Sent Mail")
_LIST_LINE = re.compile(rb'^\((?P<flags>[^)]*)\) (?:"[^"]*"|NIL) (?P<name>.+)$')


class _PinnedTls(imaplib.IMAP4_SSL):
    """IMAP over TLS to an address already checked, with the host name for SNI and the
    certificate check."""

    def __init__(self, host: str, address: str, port: int, timeout: float) -> None:
        self._address = address
        super().__init__(host, port, ssl_context=ssl.create_default_context(), timeout=timeout)

    def _create_socket(self, timeout: float | None) -> socket.socket:
        sock = socket.create_connection((self._address, self.port), timeout)
        wrapped: socket.socket = self.ssl_context.wrap_socket(sock, server_hostname=self.host)
        return wrapped


class _PinnedPlain(imaplib.IMAP4):
    """Port 143 to a checked address; the caller must STARTTLS before anything else."""

    def __init__(self, host: str, address: str, port: int, timeout: float) -> None:
        self._address = address
        super().__init__(host, port, timeout=timeout)

    def _create_socket(self, timeout: float | None) -> socket.socket:
        return socket.create_connection((self._address, self.port), timeout)


def guarded_connect(
    host: str, port: int, *, timeout: float, resolve: Resolve = system_resolve
) -> imaplib.IMAP4:
    """A connection to a customer's IMAP server that cannot reach our own network."""
    address = public_address(
        "imap", host, port, allowed_ports={TLS_PORT, STARTTLS_PORT}, resolve=resolve
    )
    if port == TLS_PORT:
        return _PinnedTls(host, address, port, timeout)
    conn = _PinnedPlain(host, address, port, timeout)
    try:
        conn.starttls(ssl.create_default_context())
    except (imaplib.IMAP4.error, ssl.SSLError, OSError):
        with suppress(OSError, imaplib.IMAP4.error):
            conn.shutdown()
        raise ProviderError("imap", "the server does not offer encryption (STARTTLS)") from None
    return conn


def imap_date(moment: datetime) -> str:
    """``17-Oct-2026``. Built by hand because ``strftime`` follows the machine's locale."""
    day = moment.astimezone(UTC)
    return f"{day.day:02d}-{_MONTHS[day.month - 1]}-{day.year}"


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


class ImapMailbox:
    def __init__(
        self,
        *,
        host: str,
        address: str,
        password: str,
        port: int = TLS_PORT,
        username: str | None = None,
        from_name: str = "",
        drafts_folder: str | None = None,
        sent_folder: str | None = None,
        inbox_folder: str = "INBOX",
        timeout: float = 30.0,
        connect: Callable[[], imaplib.IMAP4] | None = None,
        resolve: Resolve = system_resolve,
    ) -> None:
        if not host or not address or not password:
            raise ProviderAuthError("imap", "the server, the address and the password are needed")
        self.address = address
        self._username = username or address
        self._password = password
        self._from_name = from_name
        self._folders = {"drafts": drafts_folder, "sent": sent_folder}
        self._inbox = inbox_folder
        self._connect = connect or (
            lambda: guarded_connect(host, port, timeout=timeout, resolve=resolve)
        )

    # ------------------------------------------------------------------ the port

    def append_draft(self, draft: OutgoingDraft) -> str:
        message = build_message(draft, from_address=self.address, from_name=self._from_name)
        with self._session() as conn:
            drafts = self._folder(conn, "drafts")
            status, response = conn.append(
                _quote(drafts) if " " in drafts else drafts,
                r"(\Draft)",
                imaplib.Time2Internaldate(time.time()),
                message.as_bytes(),
            )
            if status != "OK":
                raise ProviderError("imap", f"APPEND to {drafts} failed: {response!r}")
        return str(message["Message-ID"])

    def draft_exists(self, remote_draft_id: str) -> bool:
        with self._session() as conn:
            self._select(conn, self._folder(conn, "drafts"), readonly=True)
            return bool(self._uids(conn, "HEADER", "Message-ID", _quote(remote_draft_id)))

    def delete_draft(self, remote_draft_id: str) -> int:
        """Remove our draft, and only it: by UID, then ``UID EXPUNGE`` (RFC 4315). A plain
        ``EXPUNGE`` would also purge anything else the person had flagged for deletion, so on
        a server without UIDPLUS the draft is only flagged, and the mail program removes it."""
        with self._session() as conn:
            self._select(conn, self._folder(conn, "drafts"), readonly=False)
            uids = self._uids(conn, "HEADER", "Message-ID", _quote(remote_draft_id))
            if not uids:
                return 0
            uid_set = ",".join(uids)
            status, data = conn.uid("STORE", uid_set, "+FLAGS.SILENT", r"(\Deleted)")
            if status != "OK":
                raise ProviderError("imap", f"cannot flag the draft: {data!r}")
            if "UIDPLUS" in _capabilities(conn):
                # imaplib has no UID EXPUNGE helper; this is the plain protocol command.
                status, data = conn._simple_command("UID", "EXPUNGE", uid_set)
                if status != "OK":
                    raise ProviderError("imap", f"UID EXPUNGE failed: {data!r}")
            else:
                log.warning("imap_no_uidplus", left_flagged=len(uids))
            return len(uids)

    def list_sent(self, since: datetime) -> list[SentMessage]:
        return [m for m in map(sent_message, self._read("sent", since)) if m is not None]

    def list_inbox(self, since: datetime) -> list[InboundMessage]:
        return [m for m in map(inbound_message, self._read(self._inbox, since)) if m is not None]

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
                conn.login(self._username, self._password)
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

    def _folder(self, conn: imaplib.IMAP4, role: str) -> str:
        """The Drafts or Sent folder: as configured, else the one the server marks with
        SPECIAL-USE (``\\Drafts``, ``\\Sent``), else a common name that exists."""
        known = self._folders.get(role)
        if known:
            return known
        listed = _list_folders(conn)
        flag = b"\\Drafts" if role == "drafts" else b"\\Sent"
        marked = [name for name, flags in listed if flag in flags]
        names = {name for name, _ in listed}
        common = [n for n in (DRAFTS_NAMES if role == "drafts" else SENT_NAMES) if n in names]
        candidates = marked or common
        if not candidates:
            raise ProviderError(
                "imap", f"cannot find the {role.title()} folder; name it in Settings"
            )
        self._folders[role] = candidates[0]
        return candidates[0]

    @staticmethod
    def _search(conn: imaplib.IMAP4, *criteria: str) -> list[str]:
        status, data = conn.search(None, *criteria)
        if status != "OK":
            raise ProviderError("imap", f"SEARCH failed: {data!r}")
        first = data[0] if data else None
        return first.decode("ascii").split() if isinstance(first, bytes) else []

    @staticmethod
    def _uids(conn: imaplib.IMAP4, *criteria: str) -> list[str]:
        status, data = conn.uid("SEARCH", *criteria)
        if status != "OK":
            raise ProviderError("imap", f"UID SEARCH failed: {data!r}")
        first = data[0] if data else None
        return first.decode("ascii").split() if isinstance(first, bytes) else []

    def _read(self, folder: str, since: datetime) -> list[EmailMessage]:
        """Messages in ``folder`` (a name, or the role ``sent``) dated at or after ``since``,
        newest first."""
        cutoff = since.astimezone(UTC)
        messages: list[EmailMessage] = []
        with self._session() as conn:
            name = self._folder(conn, folder) if folder in self._folders else folder
            self._select(conn, name, readonly=True)
            numbers = self._search(conn, "SINCE", imap_date(cutoff))
            for number in reversed(numbers[-MAX_MESSAGES_PER_LIST:]):
                status, data = conn.fetch(number, "(BODY.PEEK[])")
                raw = _raw_bytes(data) if status == "OK" else None
                if raw is None:
                    continue
                parsed = parse(raw)
                when = date_of(parsed) if parsed else None  # SINCE is by day: filter exactly
                if parsed is not None and when is not None and when >= cutoff:
                    messages.append(parsed)
        return messages


def _capabilities(conn: imaplib.IMAP4) -> set[str]:
    """What the server supports, asked again after login (servers often add to the list)."""
    status, data = conn.capability()
    if status == "OK" and data and isinstance(data[0], bytes):
        return set(data[0].decode("ascii", "replace").upper().split())
    return {c.upper() for c in getattr(conn, "capabilities", ())}


def _list_folders(conn: imaplib.IMAP4) -> list[tuple[str, bytes]]:
    """Every folder's name and its attributes, from ``LIST "" "*"``."""
    status, data = conn.list()
    if status != "OK":
        raise ProviderError("imap", f"LIST failed: {data!r}")
    found = []
    for line in data or []:
        if not isinstance(line, bytes):
            continue
        match = _LIST_LINE.match(line.strip())
        if match:
            name = match.group("name").decode("utf-8", "replace").strip()
            found.append((name[1:-1] if name.startswith('"') else name, match.group("flags")))
    return found


def _raw_bytes(data: Any) -> bytes | None:
    for part in data or []:
        if isinstance(part, tuple) and len(part) > 1 and isinstance(part[1], bytes):
            return part[1]
    return None
