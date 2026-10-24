# Phase 6c — Onboarding, Settings and mailboxes

**Goal:** an invited company sets itself up in the browser, with nothing in `.env`:
- company profile;
- sender identity;
- its own mailbox;
- a first campaign and first leads.

**Depends on:** 6b.

**Gate:**
- An invited customer gets a draft into its own **Microsoft 365** mailbox and its own **IMAP** mailbox, using only the browser.
- The contract tests pass for the IMAP, Graph and Gmail adapters.
- No mailbox setting is left in `config.py`.
- The crypto, SSRF and token-refresh-race tests pass.

## Scope

**In:**
- encrypted credentials;
- three mailbox adapters: IMAP (hardened), Microsoft Graph and the Gmail API;
- the OAuth flows;
- delivery, Sent sync and draft deletion per mailbox;
- a sender identity per mailbox;
- the onboarding wizard and the server-side setup check;
- the Settings layout;
- the intake webhook per workspace;
- the DNS check upgrade;
- the workspace-creation service;
- **applying for Google and Microsoft app verification**, which takes weeks.

**Out:**
- sending and SMTP (Phase 5);
- reading the inbox (Phase 4).

## Tasks

### 6c.1 Migration 0011

- [x] **`mailboxes`:**
  - `gateway` gains `gmail` and `graph`, beside `imap` (the `MailboxGateway` enum);
  - `owner_user_id`;
  - `is_default`, with a partial unique index (one default per workspace);
  - status `needs_reconnect`;
  - `sender` (JSON: name, title, signature, greeting, style examples);
  - `connection` (JSON: host, port, folders);
  - `last_checked_at`.
  - `credentials_ref` becomes nullable and names a credential.
- [x] **`credentials`** (a tenant table):
  - `name`, unique per workspace;
  - `purpose` (`mailbox_oauth`, `mailbox_password`, `intake_webhook`);
  - `key_version`, `nonce`, `ciphertext`;
  - `version`, for compare-and-swap;
  - `expires_at`, `details` (JSON: scopes). Named `details`: `metadata` is reserved by SQLAlchemy.
- [x] **`campaigns.mailbox_id`:** the sender for that campaign.

### 6c.2 Encrypted credentials

- [x] **`outbound/db/crypto.py`:** AES-256-GCM through the `cryptography` library.
  - The associated data is `workspace_id|credential_id`, so a ciphertext copied into another row fails to decrypt.
  - Keys come from `SECRETS_KEYS` in Doppler, shaped `{version: key}`.
  - `outbound secrets rotate` re-encrypts everything under the newest key.
- [x] **`CredentialRepository`** (scoped to the workspace): get, put, and compare-and-swap on `version`.
- [x] **Secrets never reach logs.** A redaction test checks this.

### 6c.3 Harden the IMAP adapter (`providers/adapters/imap_mailbox.py`)

- [x] **Delete by UID:** search, store and `UID EXPUNGE`. Today's plain `EXPUNGE` (`:116-124`) removes *every* message flagged `\Deleted` in the folder.
- [x] **Folders:** find Drafts and Sent through SPECIAL-USE, falling back to the mailbox's `connection` settings.
- [x] **SSRF guard:**
  - resolve the host once;
  - refuse private, loopback, link-local and metadata ranges;
  - connect to the resolved IP with SNI;
  - allow only ports 993 and 143;
  - require TLS.

  Built in `outbound/providers/netguard.py` and `guarded_connect` in the adapter. A server without UIDPLUS gets the draft flagged `\\Deleted` but not expunged, so nothing else in the folder is ever purged.
- [x] **Login** comes from the mailbox's credential, not from `Settings`.

### 6c.4 Microsoft Graph adapter (`providers/adapters/ms_graph.py`)

- [x] **OAuth:** authorization code with PKCE, through `providers/oauth.py`. Scopes: `Mail.ReadWrite offline_access User.Read`.
- [x] **The `Mailbox` port** (`providers/ports.py:235-252`):
  - `append_draft`: `POST /me/messages`, tagged with a single-value extended property that holds our message id;
  - `draft_exists`: a filter on that property;
  - `delete_draft`;
  - `list_sent`: Sent Items since a time;
  - `list_inbox`: implemented and contract-tested, but not called until Phase 4.
- [ ] **Refresh tokens rotate:**
  - a `TokenStore` port does compare-and-swap on the credential row;
  - refreshes run outside any transaction;
  - `invalid_grant` sets `needs_reconnect`.
- [ ] **Live check first:** draft, find, delete and send from Outlook. Record whether our tag and Message-ID survive.
- [ ] **The Entra app:** multi-tenant. Start publisher verification now; it needs a Microsoft AI Cloud Partner Program ID. Some customers' tenants need admin consent.

### 6c.5 Gmail adapter (`providers/adapters/gmail_api.py`)

- [x] **Scopes:** `gmail.compose` and `gmail.readonly`.
- [x] **Operations:**
  - `drafts.create` with the raw message;
  - `draft_exists`: an `rfc822msgid:` search. If the live check shows Gmail does not keep our Message-ID, fall back to the stored provider draft id;
  - `drafts.delete`;
  - `list_sent`: `in:sent after:`.
- [ ] **Google Cloud:**
  - **Publish the consent screen "In production"** while still unverified, because refresh tokens issued in Testing mode expire after 7 days.
  - Users see the unverified-app warning, and the app is capped at 100 users. Both are fine for the alpha.
  - A customer's Workspace admin can mark the app trusted.
  - Apply for verification now. The CASA assessment for restricted scopes is needed before the public launch (6f).

### 6c.6 The mailbox service and wiring

- [x] **`services/mailboxes.py`:** connect, test, pause, resume, set the default, disconnect (revoke at the provider, delete the credential) and reconnect.
  - OAuth returns to an app page, which posts `code` and `state` to the API.
  - `state` and the PKCE verifier live in the session row (`sessions.data`).
- [x] **`MailboxResolver`** replaces the single env mailbox, `Providers.mailbox` (`pipeline.py:105, 172-174`):
  - `DeliverStage` uses the message's mailbox;
  - `SentSync` goes through each mailbox in the workspace;
  - `PrivacyService` (`api/app.py:150`) deletes drafts in the mailbox that holds them.
- [x] **Copy chooses the sender:** the campaign's `mailbox_id`, else the workspace default. It sets `messages.mailbox_id`, which is never set today. The signature comes from that mailbox's `sender` JSON, falling back to the workspace profile.
- [x] **Health job** (part of the tick):
  - it refreshes tokens and marks `needs_reconnect`, with a banner and an email to the mailbox's owner and the workspace admins;
  - deliveries through that mailbox wait and resume after reconnecting;
  - when a mailbox is removed, its approved emails are held until another mailbox is chosen.
- [ ] **Remove** `IMAP_*`, `EMAIL_*`, `FROM_NAME` and the folder settings from `config.py` and `.env.example`. `scripts/migrate_first_tenant.py` moves today's mailbox into tenant #1, with its password encrypted.
- [x] **Permissions:** members connect and edit only their own mailboxes (`mailboxes.own`); admins manage all of them (`mailboxes.manage`).

### 6c.7 Company profile and sender identity

- [ ] **The workspace profile** (today's `sender_profile`) keeps the company and legal fields.
- [ ] **The mailbox's `sender`** holds the person: name, title, signature, greeting, style examples. The copy stage prefers it.
- [x] **`services/workspaces.py`** replaces `services/seed.py` for creating a workspace. It seeds:
  - the slug;
  - the country rules (`domain/policy_seeds.py`);
  - an empty default campaign.
- [x] **`services/defaults.py` loses Quantra Energy's profile and ideal customer.** New workspaces start empty, and the copy stage's `reviewed_at` gate stays.
- [ ] **Optional "Fill from our website":** one metered research call proposes profile fields, and the user reviews them before saving.

### 6c.8 Onboarding, setup check and Settings

- [x] **The wizard,** after the invite is accepted:
  1. workspace details (prefilled when an admin created the workspace) and accepting the DPA;
  2. company profile;
  3. sender identity;
  4. connect a mailbox, with its DNS health;
  5. first campaign;
  6. first leads.

  Steps after the first can be skipped and resumed.
- [x] **`GET /api/setup`** returns each setup item as ok, warning or missing, with the fix. It replaces the browser-side check in `web2/src/pages/Settings.tsx:39-95`. The Dashboard shows **Get started** until everything is green.
- [x] **Settings sections:**
  - **Account:** profile, password, sessions.
  - **Workspace:** General, Company profile, Mailboxes & senders, Deliverability, Compliance, Team, Plan & usage (6d), Integrations, Data & privacy.

  `/mailboxes` moves into Settings and redirects there. *(Mailboxes tab, OAuth return page `/oauth/callback` and the redirect are built.)*
- [ ] **New UI parts:** toast, stepper, drawer, radio group, tooltip.
- [ ] **Kept up to date:** the tour, [../USER_MANUAL.md](../USER_MANUAL.md) and `screens.spec.ts`.

### 6c.9 Deliverability and integrations

- [x] **The DNS check** (`services/dns_check.py`) gains:
  - MX;
  - the SPF lookup count (at most 10);
  - DKIM through the provider's selector (`google`; `selector1` and `selector2`) or one the user enters, instead of today's fixed list;
  - the DMARC policy and its `rua`.

  Each finding comes with fix steps in plain words.
- [x] **The intake webhook per workspace:** `POST /api/intake/webhook/{workspace_id}`, signed with that workspace's own secret (a credential). Settings → Integrations shows it and can rotate it. The global `INTAKE_WEBHOOK_SECRET` goes.

## Tests that must exist

- **Crypto:** round trip, a tampered ciphertext refused, the wrong associated data refused, key rotation.
- **IMAP:**
  - UID fixtures, including that a neighbouring `\Deleted` message survives;
  - SPECIAL-USE discovery;
  - SSRF cases: private IPs, metadata, DNS answers that change, wrong ports.
- **Contract tests** for Graph and Gmail, from fixtures built from the vendors' documentation, the same as for IMAP.
- **The token-refresh race:** two refreshes, one wins, and no token is lost.
- **Copy sets `messages.mailbox_id`,** and the signature follows the mailbox.
- **Delivery waits while a mailbox needs reconnecting.**
- `GET /api/setup`.
- The per-workspace webhook signature.
- The DNS check, with mocked answers.
- **Playwright:** invite → wizard → connect a fake mailbox → first run → draft.

## Gate record

- Date:
- Microsoft 365 draft (customer, via the browser):
- IMAP draft (customer, via the browser):
- Live checks (Graph, Gmail Message-ID behaviour):
- Google and Microsoft verification applications (dates):
- Checked by:
