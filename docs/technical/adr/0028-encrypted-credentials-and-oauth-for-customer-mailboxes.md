---
type: reference
status: accepted
date: 2026-10-23
deciders: "@rahul-trip"
introduced_in: 32b033c, c014d04, 291bb7c
---

# 0028. Encrypted-at-rest credentials, OAuth for Microsoft/Google, and an SSRF guard for customer-supplied IMAP hosts

## Context

Phase 3b's single operator mailbox was configured once, by the operator, from the environment (`IMAP_HOST`, `EMAIL_ADDRESS`, `EMAIL_PASSWORD`) — secrets that never touched the database. Every workspace now connects its own mailbox, which means a password or OAuth token supplied by a customer has to be stored *somewhere* the platform controls, and two new risks appear that did not exist when the operator configured their own trusted server: the platform now holds other people's mailbox secrets, and a customer can type in any hostname, including one that resolves inside the platform's own network.

## Decision

Mailbox credentials (an IMAP app password, or an OAuth access/refresh token pair) are stored as `CredentialRow`s: AES-256-GCM ciphertext plus a nonce, keyed by `SECRETS_KEYS` (versioned, so rotation means adding a new version and letting old ones age out), with associated data bound to `"{workspace_id}|{credential_id}"` — ciphertext copied to a different row, even within the same workspace, fails to decrypt. Microsoft 365 and Google Workspace are connected via OAuth 2.0 authorization code with PKCE (RFC 7636), using one multi-tenant OAuth app per provider (not one per customer); refresh tokens are rotated or retained per each provider's own behaviour, and a refused refresh raises `ReconnectNeeded` rather than a generic error. A customer-supplied IMAP host is resolved once by `outbound/providers/netguard.py::public_address`, which refuses the connection if any resolved address is non-global or multicast, and connects to the specific address it checked (not a fresh re-resolution), closing the DNS-rebinding gap where a second lookup could answer differently from the first.

## Consequences

- **Good:** a compromised database dump contains no usable mailbox secret without `SECRETS_KEYS`, and even with the key, a row cannot be replayed under a different workspace or credential id. OAuth means the platform never sees or stores a customer's actual Microsoft/Google password at all. The SSRF guard closes a real, not hypothetical, risk — a customer (or a stolen account) typing `169.254.169.254` or an internal hostname as their "IMAP server."
- **Bad:** `SECRETS_KEYS` becomes a single point of failure for every workspace's mailbox credentials at once — losing it means every stored credential becomes unrecoverable (not decryptable even by the platform), which is the correct trade-off for a secret but raises the operational stakes of key management and backup.
- **Follow-ups:** the Microsoft and Google OAuth apps are not yet verified/published with either platform, so new customers see an "unverified app" warning during consent — tracked as an open item, not a code gap.

## Alternatives considered

| Option | Why not |
|---|---|
| Store credentials in plaintext, rely on database access control alone | A single compromised database connection or backup exposes every customer's mailbox at once; encryption at rest is the standard mitigation for exactly this |
| Let a customer supply IMAP credentials over basic auth for Microsoft/Google too | Both platforms are actively removing IMAP basic auth; OAuth is the only forward-compatible path, and is also the lower-trust option (narrower, revocable scopes rather than a full password) |
| Re-resolve the IMAP hostname at connect time instead of connecting to the checked address | Reopens the exact DNS-rebinding gap the guard exists to close |

## Evidence in the code

- `outbound/db/crypto.py::Keyring`; `outbound/db/models.py::CredentialRow`.
- `outbound/providers/oauth.py`; `outbound/providers/adapters/ms_graph.py`, `gmail_api.py`.
- `outbound/providers/netguard.py::public_address`.
- `tests/providers/test_netguard.py`, `test_oauth.py`, `test_ms_graph.py`, `test_gmail_api.py`, `test_imap_mailbox.py`.
