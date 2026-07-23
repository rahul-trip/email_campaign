# Agent Integration Metadata (apgent)

This file tracks workspace metadata for collaboration between different agentic frameworks and AI tools (such as Claude Code, Cursor, Aider, and Antigravity).

## Workspace Overview
- **Project Name:** AI-Driven Outbound Sales Funnel Engine & HIP Dashboard
- **Active Specification:** [system_specification.md](file:///Users/cnc/Downloads/email_capaign/system_specification.md)

## Active Files
- Specification: [system_specification.md](file:///Users/cnc/Downloads/email_capaign/system_specification.md)
- Claude Metadata: [Claude.md](file:///Users/cnc/Downloads/email_capaign/Claude.md)
- Memory Log: [memory.md](file:///Users/cnc/Downloads/email_capaign/memory.md)
- Agent Metadata: [apgent.md](file:///Users/cnc/Downloads/email_capaign/apgent.md)
- Agentic System Plan: [AGENTIC_SYSTEM_PLAN.md](file:///Users/cnc/Downloads/email_capaign/AGENTIC_SYSTEM_PLAN.md)

## Built Components

### agent/tools/mailer/ — Module F v0 (Campaign-to-Drafts), now a tool under agent/
- [agent/tools/mailer/](file:///Users/cnc/Downloads/email_capaign/agent/tools/mailer/) — reads the campaign xlsx, writes one draft per row to the mailbox's Drafts folder via IMAP (Hostinger today). **Moved here from the project root** (was `mailer/`) — the agent calls it as a tool, so it lives under `agent/tools/`, called via `agent/tools/drafts_tool.py`.
- Entry point: `agent/tools/mailer/core/campaign_runner.py::sync_campaign_to_drafts()` (typed args, JSON-serializable result). Package-qualified imports throughout (`agent.tools.mailer.*`) — no more sys.path hacks.
- `start_row: int | None = None` param on `read_campaign_rows()` / `sync_campaign_to_drafts()` — used by `agent/tools/drafts_tool.py` to draft only newly-appended rows.
- **Config merged:** reads secrets from the single `agent/.env` (no separate mailer `.env` anymore). Real Hostinger credentials are set there.
- Standalone CLI: `python -m agent.tools.mailer.scripts.save_drafts` / `.list_folders` (run from project root).

### agent/ — Modules A → B → C (LangGraph Lead-Generation Pipeline)
- [agent/](file:///Users/cnc/Downloads/email_capaign/agent/) — produces rows in `Quantra_Energy_Outbound_Campaign_Matrix.xlsx` and hands off to `agent/tools/mailer/`.
- **Orchestration:** LangGraph `StateGraph` with 7 nodes + 2 conditional routers.
- **Providers (Strategy pattern, each behind an ABC):**
  | Stage | Provider | Key env var |
  |-------|----------|-------------|
  | Discovery | `TavilyDiscoveryProvider` (default) or `GoogleCseDiscoveryProvider` | `TAVILY_API_KEY` or `GOOGLE_CSE_KEY`+`GOOGLE_CSE_CX` |
  | Contacts | `BrightDataContactProvider` (default) or `ProxycurlContactProvider` | `BRIGHTDATA_API_KEY`+`BRIGHTDATA_LINKEDIN_DATASET_ID` or `PROXYCURL_API_KEY` |
  | Email Finder | `HunterEmailFinder` | `HUNTER_API_KEY` |
  | Email Verifier | `NeverBounceVerifier` | `NEVERBOUNCE_API_KEY` |
  | Copywriter | `TemplateCopywriter` or `LlmCopywriter` | — or per `llm.provider` |
- **CLI:** `python -m agent.main --config agent/config.yaml [--dry-run] [--max-companies N] [--max-leads N] [--no-drafts]`
- **Tests:** 56 passing (agent + mailer), zero network calls — `python -m pytest agent/ -q`
- **Discovery swapped to Tavily** (default; Google CSE kept, selectable via `providers.discovery: google_cse`). Shared domain-filtering logic factored into `agent/providers/discovery/_common.py`.
- **Contacts swapped to Bright Data LinkedIn Scraper** (default; Proxycurl kept, selectable via `providers.contacts: proxycurl`). Bright Data's Dataset API is async (trigger snapshot → poll → fetch) — different shape than every other provider. User must confirm `BRIGHTDATA_LINKEDIN_DATASET_ID` points at a "LinkedIn People Search"-shaped collector; see docstring in `agent/providers/contacts/brightdata.py`.
- **Sender Profile & LLM Copywriter — Built:** `config.sender` (SenderProfile) + `config.llm` (LlmConfig, one flat block — the earlier multi-endpoint `llm_endpoints` registry idea was dropped as unneeded for a single LLM task). `providers/copywriter/template_stub.py` is fully de-hardcoded (no more literal "Quantra Energy"). `providers/copywriter/llm_copywriter.py` is a new SDK-free adapter supporting `anthropic` | `openai` | `gemini` | `ollama` | `github_copilot` | `openai_compatible` via a single OpenAI-compatible `/chat/completions` call. Switch with `providers.copywriter: llm` in config.yaml.
- **Config files to create before running:**
  - `agent/config.yaml` (copy from `agent/config.example.yaml`) — fill in `campaign:` and at minimum `sender.company_name`
  - `agent/.env` (copy from `agent/.env.example`; fill in API keys) — single env file for the whole `agent/` tree, including `agent/tools/mailer/`
  - `agent/sender_profile.md` (copy from `agent/sender_profile.example.md`) — only required if `providers.copywriter: llm`
