# Claude Metadata & Context

This workspace is set up to develop an AI-Driven Outbound Sales Funnel Engine & HIP Dashboard.

## Current Workspace State
- Initialized [system_specification.md](file:///Users/cnc/Downloads/email_capaign/system_specification.md) containing the structured, deterministic system specification.
- Initialized metadata/integration files:
  - [Claude.md](file:///Users/cnc/Downloads/email_capaign/Claude.md)
  - [apgent.md](file:///Users/cnc/Downloads/email_capaign/apgent.md)
  - [memory.md](file:///Users/cnc/Downloads/email_capaign/memory.md)

## Development Workflow Instructions
- Refer to [system_specification.md](file:///Users/cnc/Downloads/email_capaign/system_specification.md) for architectural topology, schema design, and modular goals.
- Prioritize high-quality coding practices, robust error handling for edge cases, and asynchronous worker safety.

## Built: agent/tools/mailer/ (Module F v0) — moved under agent/tools/ as a called tool
- A standalone, provider-agnostic tool exists at [agent/tools/mailer/](file:///Users/cnc/Downloads/email_capaign/agent/tools/mailer/) that reads `Quantra_Energy_Outbound_Campaign_Matrix.xlsx` and saves one draft per row to the mailbox's Drafts folder (To = Direct Business Email, Subject = Organization URL, Body = Tailored Pitch Email only). **Originally at project-root `mailer/`, moved into `agent/tools/mailer/` per user request** ("the agent should call it as a tool") — imports are now package-qualified (`agent.tools.mailer.*`), no sys.path hacks.
- Current provider: Hostinger via plain IMAP APPEND. Swapping providers later is a config change (same-IMAP host) or a single new class under `agent/tools/mailer/drafts/` implementing `DraftProvider` (OAuth APIs like Gmail/Outlook) — no changes needed in `ingestion/` or `core/campaign_runner.py`.
- `sync_campaign_to_drafts()` accepts an optional `start_row` parameter (default None = all rows, backward-compatible). The agent uses this to draft only newly-appended rows, via `agent/tools/drafts_tool.py::run_drafts_sync()`.
- **Config/env merged into `agent/.env`** (single file for the whole `agent/` tree) — user's real Hostinger credentials (`EMAIL_ADDRESS`, `EMAIL_PASSWORD`, `IMAP_HOST=imap.hostinger.com`, `DRAFTS_FOLDER=INBOX.Drafts`, `FROM_NAME`, `XLSX_PATH`) are already set there. `requirements.txt`, `.gitignore` also merged into `agent/`'s versions; mailer's own copies deleted. Single shared venv: `agent/.venv`.
- Tests: `agent/tools/mailer/tests/` now run together with `agent/tests/` via `python -m pytest agent/ -q` — currently 56/56 passing (42 after the mailer merge + 6 Tavily discovery + 8 Bright Data contacts).

## Built: agent/ (Modules A → B → C — LangGraph pipeline)
- New package at [agent/](file:///Users/cnc/Downloads/email_capaign/agent/) implements the upstream lead-generation engine.
- **Pipeline:** discover_companies → resolve_contacts → find_emails → verify_emails → generate_copy → persist_rows → sync_drafts
- **Provider stack (real, behind Strategy interfaces):**
  - Discovery: **Tavily Search API (default)** — `providers/discovery/tavily.py`; Google Custom Search JSON API kept as a selectable alternative — `providers/discovery/google_cse.py` (`providers.discovery: google_cse`). Shared domain-blocklist/extraction logic in `providers/discovery/_common.py`.
  - Contact resolution: **Bright Data LinkedIn Scraper API (default)** — `providers/contacts/brightdata.py`; Proxycurl kept as a selectable alternative — `providers/contacts/proxycurl.py` (`providers.contacts: proxycurl`). Bright Data's Dataset API is async — trigger a snapshot job, poll `/progress` until ready, fetch `/snapshot`; every other provider in this codebase is a single synchronous call. Needs `BRIGHTDATA_API_KEY` + `BRIGHTDATA_LINKEDIN_DATASET_ID` (account-specific — user creates a LinkedIn People Search collector in their Bright Data dashboard).
  - Email finding: Hunter.io Email Finder (`providers/email_finder/hunter.py`)
  - Email verification: NeverBounce single-check (`providers/verifier/neverbounce.py`)
  - Copywriter: Deterministic template stub (`providers/copywriter/template_stub.py`) — **LLM adapter TODO**
- **Config:** non-secret run config in `agent/config.yaml`; secrets (API keys) in `.env`.
- **Orchestration:** LangGraph `StateGraph`; all nodes wrapped with `@logged_step` decorator.
- **Persistence:** `XlsxLeadRepository` — only module that writes the xlsx; header-mapped, never touches existing rows.
- **Tests:** 22 passing (no network, no real keys) — `python -m pytest agent/tests/ -q`
- **CLI:** `python -m agent.main [--dry-run] [--max-companies N] [--max-leads N] [--no-drafts]`
- **Sender Profile & Generic LLM Copywriter — Built:** `config.sender` (`SenderProfile`: structured facts from `config.yaml`'s `sender:` block + a `narrative` field read verbatim from `sender_profile.md`) and `config.llm` (`LlmConfig`: one flat block — provider/model/base_url/key_env/temperature/max_tokens). The originally-planned `llm_endpoints:` multi-endpoint registry was intentionally simplified away (only one LLM task exists today; add the registry back if/when a second one appears).
  - `TemplateCopywriter` is fully de-hardcoded (reads everything from `config.sender`) and no longer opens with the banned phrase "I hope this finds you well".
  - `LlmCopywriter` (`agent/providers/copywriter/llm_copywriter.py`) is SDK-free — a single `requests.post` to an OpenAI-compatible `/chat/completions` endpoint. Provider presets: `anthropic`, `openai`, `gemini`, `ollama` (local), `github_copilot` (requires extra `Editor-Version`/`Copilot-Integration-Id` headers, key `COPILOT_API_KEY`), `openai_compatible` (Groq/Together/etc., user sets `base_url`+`key_env`).
  - Switch copywriters with one line: `providers.copywriter: template` (default, no keys) or `llm`.
  - Tests: 40/40 passing in `agent/tests/` (`python -m pytest agent/tests/ -q`), mailer regression 2/2 still passing.
  - Blocked on: user has not yet created `agent/config.yaml` or `agent/sender_profile.md` (only `.example` templates exist) or provided the four data-provider API keys.
