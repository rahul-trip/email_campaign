---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# IMAP mailbox

| | |
|---|---|
| **Role** | Save approved emails as drafts; check and delete drafts; read the Sent folder (and, from Phase 4, the inbox) |
| **Port** | `Mailbox` |
| **Adapter** | `outbound/providers/adapters/imap_mailbox.py::ImapMailbox` (standard `imaplib`; any IMAP server) |
| **Registry** | `build_mailbox_if_configured`: only when `IMAP_HOST` and `EMAIL_ADDRESS` are set |
| **Settings** | `IMAP_HOST`, `IMAP_PORT` (993), `IMAP_USE_SSL` (true), `EMAIL_ADDRESS`, `EMAIL_PASSWORD`, `FROM_NAME`, `DRAFTS_FOLDER` (`INBOX.Drafts`), `SENT_FOLDER` (`INBOX.Sent`), `INBOX_FOLDER`, `IMAP_TIMEOUT_SECONDS` (30) |
| **Price** | None (not metered) |
| **Cache** | None |
| **Status** | Live-checked 2026-10-19: login, save a draft, find it, delete it |

## Operations

Each operation opens its own short IMAP session and logs out, which suits a pass that runs and exits.

| Operation | IMAP |
|---|---|
| `append_draft(draft)` | Builds the message (From, To, Subject, `Message-ID`, body) and `APPEND`s it to the drafts folder with the `\Draft` flag |
| `draft_exists(id)` | `SEARCH HEADER Message-ID "<id>"` in the drafts folder |
| `delete_draft(id)` | The same search, then flag the matches deleted and `EXPUNGE`; returns the count |
| `list_sent(since)` | `SEARCH SINCE <date>` in the Sent folder, read-only, newest first, at most 500 messages, parsed into `SentMessage` |
| `list_inbox(since)` | The same on the inbox, into `InboundMessage` (not used until Phase 4) |

## Errors

A failed `APPEND` or `SEARCH` raises `ProviderError("imap", …)`; socket timeouts and login failures raise from `imaplib`. **There are no retries**: deliver defers the lead an hour, and the Sent sync fails its job until the next tick.

## Limits and quirks

- Folder names differ between providers (`INBOX.Drafts` against `Drafts`); set them to match the server.
- The mailbox in use is the one in the settings, not the `mailboxes` table ([R-20](../tech-debt-and-risks.md#r-20--note--designed-but-not-built-inbound-mail-and-the-mailbox-table-b8)).
- An OAuth-only provider (Google Workspace, Microsoft 365 with basic auth off) needs a different adapter behind the same port.

## Tests

`tests/providers/test_imap_mailbox.py` runs against an in-memory IMAP server (no fixtures).

## Data sent to the vendor

The mailbox provider stores the drafts (recipient address, subject, body), and the operator's sent mail is read back.
