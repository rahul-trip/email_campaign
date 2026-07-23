# Mailer — Campaign-to-Drafts Sync Tool

Reads `Quantra_Energy_Outbound_Campaign_Matrix.xlsx` and saves one draft email
per row directly into your mailbox's **Drafts** folder — nothing is sent.

- **To:** `Direct Business Email`
- **Subject:** `Organization URL`
- **Body:** `Tailored Pitch Email`

`Follow-up Text`, `Points of Commonality`, `POC Details & Eccentricities`, and
`Specific Person to Contact` are intentionally ignored — that context is
already folded into the pitch email body by the upstream copywriting step.

This tool lives at `agent/tools/mailer/` and is invoked by the LangGraph
agent as its final pipeline step (Module F) via
[`agent/tools/drafts_tool.py`](../drafts_tool.py). It's built as a plain,
typed Python function with a JSON-serializable result — framework-free, so
it's also fully usable standalone from the command line (below).

Configuration is shared with the rest of the agent: this tool reads its
settings from `agent/.env` (see [`../../.env.example`](../../.env.example)),
not a `.env` file of its own — there's only one env file for everything
under `agent/`.

## Directory layout

```
agent/tools/mailer/
  config/
    settings.py        # loads agent/.env -> typed Settings; only place that knows raw env vars
  ingestion/
    xlsx_reader.py      # reads only the 3 required columns, skips incomplete rows
  drafts/
    base.py             # DraftProvider interface — implement this for a new provider
    imap_provider.py     # IMAP APPEND implementation (Hostinger today; any IMAP host)
    __init__.py          # provider registry / factory (get_provider)
  core/
    message_builder.py   # builds the RFC822 email (From/To/Subject/Body)
    campaign_runner.py    # sync_campaign_to_drafts() — the actual tool entry point
  scripts/
    save_drafts.py       # thin CLI wrapper for manual runs
    list_folders.py       # one-off: prints your mailbox's IMAP folder names
  tests/
    test_xlsx_reader.py
  data/                  # (empty) future home for campaign input files
  logs/                  # (empty) future home for run logs
  README.md
```

## Configuration needed from you

Fill these into `agent/.env` (copy `agent/.env.example` → `agent/.env` if you
haven't already — it's gitignored):

| Variable | What it is | Notes |
| --- | --- | --- |
| `EMAIL_ADDRESS` | Your full Hostinger mailbox address | e.g. `sales@yourdomain.com` |
| `EMAIL_PASSWORD` | Mailbox password | Use an app-specific password if you turn on 2FA for this mailbox |
| `IMAP_HOST` | IMAP hostname | Hostinger's is typically `imap.hostinger.com` — confirm in hPanel → Emails → Connect Apps/Devices, since custom-domain hosting plans sometimes use a different host |
| `IMAP_PORT` / `IMAP_USE_SSL` | Defaults are `993` / `true` | Standard IMAP-over-SSL; only change if Hostinger's docs say otherwise for your plan |
| `DRAFTS_FOLDER` | Exact IMAP folder name for Drafts | Often `Drafts`, sometimes `INBOX.Drafts`. Run `python -m agent.tools.mailer.scripts.list_folders` after filling in the fields above to see the exact name for your mailbox and paste it here |
| `FROM_NAME` | Display name for the "From" header | e.g. `Rahul, Quantra Energy` |
| `XLSX_PATH` | Path to the campaign workbook | Defaults to the `Quantra_Energy_Outbound_Campaign_Matrix.xlsx` at the project root if left blank |
| `DELAY_SECONDS` | Pause between each draft write | Default `1` second — polite delay so shared hosting IMAP doesn't rate-limit the connection |

You don't need to set up OAuth or an API key for Hostinger — plain IMAP with
the mailbox's own login credentials is enough.

## Running it standalone

All commands below run from the **project root** (`email_capaign/`), since
this tool is now a subpackage of `agent`:

```bash
pip install -r agent/requirements.txt
cp agent/.env.example agent/.env    # then fill in the values above

# 1. Preview what would be drafted (no mailbox connection, nothing written)
python -m agent.tools.mailer.scripts.save_drafts --dry-run

# 2. Once EMAIL_ADDRESS/EMAIL_PASSWORD/IMAP_HOST/DRAFTS_FOLDER are set, confirm
#    the exact Drafts folder name for your mailbox:
python -m agent.tools.mailer.scripts.list_folders

# 3. Do a real run, capped to 1-2 rows first to confirm a draft lands correctly:
python -m agent.tools.mailer.scripts.save_drafts --limit 2

# 4. Full run:
python -m agent.tools.mailer.scripts.save_drafts
```

Each run prints a JSON summary (`total_rows`, `drafted`, `failed`, per-row
`results`). A row is skipped from processing entirely if it has no recipient
email or no pitch body — nothing is drafted for it, no error raised.

## Switching email providers later

Everything provider-specific lives behind `drafts/base.py`'s `DraftProvider`
interface:

- **Staying on IMAP but changing host** (e.g. moving off Hostinger to another
  IMAP-based mailbox): change `IMAP_HOST`, `EMAIL_ADDRESS`, `EMAIL_PASSWORD`,
  `DRAFTS_FOLDER` in `agent/.env`. No code changes.
- **Moving to an OAuth-only API** (Gmail API, Microsoft Graph — see Module F in
  the system spec): implement a new class in `drafts/` satisfying
  `DraftProvider` (`connect`, `close`, `save_draft`), register it in
  `drafts/__init__.py`'s `_PROVIDERS` dict, and set `PROVIDER_TYPE` in `.env`.
  `ingestion/` and `core/campaign_runner.py` don't change at all.

## Called as an agent tool

The agent doesn't call this package directly — it goes through
[`agent/tools/drafts_tool.py`](../drafts_tool.py):

```python
from agent.tools.drafts_tool import run_drafts_sync

result = run_drafts_sync(xlsx_path=..., start_row=..., dry_run=False)
```

`drafts_tool.py` is the thin, LangGraph-facing wrapper; this package
(`agent.tools.mailer`) stays framework-free — it takes plain keyword
arguments and returns a plain dataclass (`CampaignSyncResult`), so it's
never coupled to LangGraph or any other agent framework.
