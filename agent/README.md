# agent/ — LangGraph Outbound Lead-Generation Agent

Upstream engine that **produces rows** in `Quantra_Energy_Outbound_Campaign_Matrix.xlsx`
and then hands them off to the Campaign-to-Drafts tool at
[`tools/mailer/`](tools/mailer/) — a self-contained subpackage the agent calls
as a tool for its final pipeline step. See
[`tools/mailer/README.md`](tools/mailer/README.md) for that tool's own docs
(it's also fully usable standalone).

## Pipeline (Modules A → B → C)

```
Discover companies → Resolve POC contact → Find email → Verify email
→ Generate copy → Persist to xlsx → Sync drafts (tools/mailer, via tools/drafts_tool.py)
```

## Quick-start

```bash
# 1. Install dependencies
pip install -r agent/requirements.txt

# 2. Configure (from project root)
cp agent/config.example.yaml agent/config.yaml   # edit keywords, location, sender:
cp agent/.env.example agent/.env                  # fill in API keys
cp agent/sender_profile.example.md agent/sender_profile.md   # only needed for copywriter: llm

# 3. Dry run (no writes, just shows what would be appended)
python -m agent.main --dry-run --max-companies 1

# 4. Live single-lead run
python -m agent.main --max-companies 1 --max-leads 1
```

## Config reference (`config.yaml`)

| Key | Description |
|-----|-------------|
| `campaign.keywords` | Keyword phrases for company discovery (Tavily by default) |
| `campaign.location` | Region string added to every search |
| `campaign.target_titles` | POC job titles in priority order |
| `limits.max_companies` | Cap on companies discovered (cost control) |
| `limits.max_leads` | Cap on rows appended per run |
| `limits.per_call_delay_seconds` | Politeness delay between API calls |
| `providers.*` | Concrete adapter to use per capability |
| `verification.keep_statuses` | NeverBounce statuses to keep |
| `verification.mark_risky_statuses` | NeverBounce statuses tagged as risky |
| `output.xlsx_path` | Relative path to the campaign matrix workbook |
| `output.run_drafts_after` | Whether to invoke the mailer tool after appending |
| `sender.*` | Who is sending the emails — only `company_name` is required. Feeds the template copywriter's commonality matching and (if `copywriter: llm`) the LLM's context |
| `sender.profile_path` | Path (relative to `config.yaml`) to a free-form narrative file, default `sender_profile.md` — passed verbatim to the LLM, never parsed |
| `llm.*` | Model settings used **only** when `providers.copywriter: llm` — see below |

## Secrets (`agent/.env`)

A single `.env` file (`agent/.env`, copied from `agent/.env.example`) covers
**everything** under `agent/`, including the mailer tool at `tools/mailer/` —
there's no separate env file to maintain per subpackage:

```
# Data providers (agent pipeline)
TAVILY_API_KEY=       # Tavily Search API key (default discovery provider)
GOOGLE_CSE_KEY=       # Google Custom Search API key (only if providers.discovery: google_cse)
GOOGLE_CSE_CX=        # Custom Search Engine ID (only if providers.discovery: google_cse)
BRIGHTDATA_API_KEY=              # Bright Data API key (default contacts/LinkedIn provider)
BRIGHTDATA_LINKEDIN_DATASET_ID=  # Bright Data dataset ID for the LinkedIn People Search collector
PROXYCURL_API_KEY=    # Proxycurl API key (only if providers.contacts: proxycurl)
HUNTER_API_KEY=       # Hunter.io API key
NEVERBOUNCE_API_KEY=  # NeverBounce API key

# LLM copywriter — only needed when providers.copywriter: llm — set the ONE
# matching llm.provider:
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
GEMINI_API_KEY=
COPILOT_API_KEY=      # for llm.provider: github_copilot

# Mailer tool (tools/mailer) — draft delivery via IMAP
PROVIDER_TYPE=imap
IMAP_HOST=imap.hostinger.com
IMAP_PORT=993
IMAP_USE_SSL=true
EMAIL_ADDRESS=
EMAIL_PASSWORD=
DRAFTS_FOLDER=Drafts
FROM_NAME=
XLSX_PATH=
DELAY_SECONDS=1
```

See [`tools/mailer/README.md`](tools/mailer/README.md) for what each mailer
variable means and how to find your exact `DRAFTS_FOLDER`.

## Sender profile & LLM copywriter

`providers.copywriter` is `template` (default, deterministic, no API key) or
`llm` (real model-generated copy). Switching is one line in `config.yaml`.

To use `llm`, you need:
1. `sender:` block in `config.yaml` filled in beyond just `company_name`
   (the richer, the better the generated commonalities).
2. `agent/sender_profile.md` — copy from `sender_profile.example.md` and
   write freely; this is passed to the model verbatim as unstructured context.
3. One API key in `.env` matching `llm.provider`.
4. `providers.copywriter: llm` in `config.yaml`.

The LLM adapter (`providers/copywriter/llm_copywriter.py`) is SDK-free — a
plain `requests.post` to an OpenAI-compatible `/chat/completions` endpoint.
Supported `llm.provider` presets:

| Preset | Default endpoint | Key env var |
|--------|-------------------|-------------|
| `anthropic` | `api.anthropic.com/v1` | `ANTHROPIC_API_KEY` |
| `openai` | `api.openai.com/v1` | `OPENAI_API_KEY` |
| `gemini` | Google's OpenAI-compatible endpoint | `GEMINI_API_KEY` |
| `github_copilot` | `api.githubcopilot.com` | `COPILOT_API_KEY` |
| `ollama` | `localhost:11434/v1` (local, no key) | — |
| `openai_compatible` | none — you set `llm.base_url` | `llm.key_env` (e.g. Groq, Together) |

Example — switch to GitHub Copilot inference:

```yaml
llm:
  provider: "github_copilot"
  model: "gpt-4o"          # any chat model your Copilot plan/token exposes
```
```
# .env
COPILOT_API_KEY=<your token>
```

> Note: GitHub Copilot's `/chat/completions` endpoint additionally requires
> `Editor-Version` and `Copilot-Integration-Id` headers beyond a bearer token
> — the `github_copilot` preset sends these automatically. If your Copilot
> token is a short-lived session token (rather than a long-lived PAT-style
> key), you may need to refresh `COPILOT_API_KEY` periodically.

## CLI flags

| Flag | Description |
|------|-------------|
| `--config PATH` | Config file (default: `agent/config.yaml`) |
| `--dry-run` | Discovery → copy with real providers, but skip writing |
| `--max-companies N` | Override `limits.max_companies` for this run |
| `--max-leads N` | Override `limits.max_leads` for this run |
| `--no-drafts` | Skip `sync_drafts` even if `run_drafts_after: true` |

## Running tests

```bash
cd /path/to/email_capaign
python -m pytest agent/ -q     # runs agent/tests/ AND agent/tools/mailer/tests/
```

## Architecture

- **Prompts**: all LLM prompt text lives in [`prompts.py`](prompts.py) at the package root — not inline in providers. Providers own *how* a prompt is sent (HTTP, retries, parsing); `prompts.py` owns *what* is said. Tune agent behavior (tone, banned phrases, structure rules) by editing that one file.
- **Strategy** pattern: one ABC per external capability; concrete adapters implement each.
- **Adapter** pattern: each provider wraps one external API, maps to domain dataclasses.
- **Repository** pattern: `persistence/lead_repository.py` is the only module that touches the xlsx.
- **Dependency Injection**: `ProviderBundle` built once in `main.py`, injected into all nodes.
- **Command nodes**: each LangGraph node is a single-responsibility pure function.
- **Tool boundary**: `tools/mailer/` is a self-contained, framework-free package (own config loading, own tests) that the agent calls through `tools/drafts_tool.py` — the same shape any future tool (CRM sync, calendar booking, ...) should follow: implement it standalone under `tools/`, then add a thin wrapper module the graph node calls.

See `AGENTIC_SYSTEM_PLAN.md` at the project root for full specification.
