# Plan — LangGraph Outbound Lead-Generation Agent (`agent/`)

## Context

The workspace already has a working **Module F** tool, `mailer/`, that reads
`Quantra_Energy_Outbound_Campaign_Matrix.xlsx` and pushes one draft per row into
the Hostinger mailbox's Drafts folder. What's missing is everything *upstream* of
that file: the system currently has no way to **produce** the rows.

This plan builds that upstream engine as a new, self-contained **LangGraph
agent** package (`agent/`) that implements the slice of
`system_specification.md` covering Modules A → B → C, plus the persistence +
draft-staging hand-off. Concretely the agent will:

1. Read a config file for a **keywords array** and **location**.
2. **Discover** relevant companies in that region (Google Custom Search).
3. **Resolve** the best point-of-contact per company (Proxycurl / LinkedIn).
4. **Find** that person's business email (Hunter.io).
5. **Verify** the email (NeverBounce), branching on the result.
6. **Generate** the content for all seven spreadsheet columns (pluggable
   copywriter, deterministic-template default for now).
7. **Append** new rows to `Quantra_Energy_Outbound_Campaign_Matrix.xlsx`.
8. As the **final step**, invoke the existing Campaign-to-Drafts tool so the new
   rows become mailbox drafts.
9. **Log every step and its status** to console + a per-run log file.

The design deliberately mirrors `mailer/`'s proven structure — Strategy
interface per external dependency, config object, framework-free core — so it
stays production-grade, SOLID, and easy to extend.

### Decisions already locked (do not re-litigate)
- **Data providers = best-of-breed, wired for real now:** Google Custom Search
  (discovery), Proxycurl (LinkedIn POC), Hunter.io (email finding), NeverBounce
  (verification). Each still sits behind a pluggable interface.
- **Copywriter = pluggable interface, deterministic template default.** No LLM
  vendor chosen yet; a real Claude/OpenAI adapter is a later drop-in.
- **Target file = the same** `Quantra_Energy_Outbound_Campaign_Matrix.xlsx` the
  drafts tool already reads. Append, never overwrite.
- **Config split:** non-secret run config in `agent/config.yaml`; secrets (API
  keys) in `.env`.
- **Orchestration = LangGraph** (`StateGraph`).

---

## Deliverable 0 — Save this plan into the repo

After approval, copy this plan to
`/Users/cnc/Downloads/email_capaign/AGENTIC_SYSTEM_PLAN.md` (next to
`system_specification.md`) so it lives with the project, then implement it.

---

## Architecture overview

One new top-level package, `agent/`, sibling to `mailer/`. It reuses `mailer/`
by importing its public function — it does **not** duplicate any mail logic.

### Design patterns to apply (call these out in code comments)
- **Strategy** — one ABC per external capability (`CompanyDiscoveryProvider`,
  `ContactResolutionProvider`, `EmailFinderProvider`, `EmailVerifierProvider`,
  `CopywriterProvider`); concrete adapters implement each. Mirrors
  `mailer/drafts/base.py::DraftProvider`.
- **Adapter** — each concrete provider wraps one external HTTP API and maps its
  response into our own dataclasses, so the rest of the code never sees vendor
  JSON.
- **Factory / Registry** — a `get_*` factory per capability picks the concrete
  class from a `{name: class}` dict keyed by config, exactly like
  `mailer/drafts/__init__.py::get_provider`.
- **Repository** — `persistence/lead_repository.py` is the only module that
  knows the xlsx layout (read existing, dedupe, append).
- **Dependency Injection** — providers are built once in a `ProviderBundle` and
  injected into nodes; nodes never construct providers themselves (keeps nodes
  unit-testable with fakes).
- **Command / single-responsibility nodes** — each LangGraph node is one pure-ish
  function doing one stage.

### SOLID mapping (for the reviewer)
- **S**: each provider/node/module has one reason to change.
- **O**: new data source = new class + registry entry, no edits to nodes.
- **L**: every concrete provider is substitutable for its ABC.
- **I**: capability interfaces are narrow (1–3 methods each).
- **D**: nodes depend on ABCs injected via `ProviderBundle`, not concretes.

---

## Directory structure to create

```
agent/
  __init__.py
  main.py                     # CLI entry point (argparse) -> builds graph, invokes it
  config.yaml                 # real run config (keywords, location, titles, limits, provider names)
  config.example.yaml         # committed template
  .env.example                # API-key template (secrets only)
  requirements.txt
  README.md
  logs/
    .gitkeep                  # per-run log files land here (gitignored except .gitkeep)

  config/
    __init__.py
    models.py                 # AgentConfig, ProviderNames dataclasses (frozen)
    loader.py                 # load_config() -> AgentConfig (reads config.yaml + .env)

  observability/
    __init__.py
    logging_setup.py          # configure_logging(run_id) -> logging.Logger (file + console)
    step_logger.py            # @logged_step decorator + StepRecord dataclass

  domain/
    __init__.py
    models.py                 # Company, Contact, EmailCandidate, VerifiedEmail, Lead, LeadColumns

  providers/
    __init__.py
    bundle.py                 # ProviderBundle dataclass + build_providers(config, secrets)
    discovery/
      __init__.py             # get_discovery_provider(name) factory/registry
      base.py                 # CompanyDiscoveryProvider(ABC)
      google_cse.py           # GoogleCseDiscoveryProvider (real)
    contacts/
      __init__.py             # get_contact_provider(name)
      base.py                 # ContactResolutionProvider(ABC)
      proxycurl.py            # ProxycurlContactProvider (real)
    email_finder/
      __init__.py             # get_email_finder(name)
      base.py                 # EmailFinderProvider(ABC)
      hunter.py               # HunterEmailFinder (real)
    verifier/
      __init__.py             # get_verifier(name)
      base.py                 # EmailVerifierProvider(ABC) + VerificationStatus enum
      neverbounce.py          # NeverBounceVerifier (real)
    copywriter/
      __init__.py             # get_copywriter(name)
      base.py                 # CopywriterProvider(ABC) + CopyOutput dataclass
      template_stub.py        # TemplateCopywriter (deterministic default)

  persistence/
    __init__.py
    lead_repository.py        # XlsxLeadRepository: existing_domains(), append_leads(), row_count()

  graph/
    __init__.py
    state.py                  # AgentState TypedDict + reducers
    nodes.py                  # one function per stage (see Node contracts below)
    build.py                  # build_graph(bundle, repo, config, logger) -> compiled graph

  tools/
    __init__.py
    drafts_tool.py            # run_drafts_sync(...) -> thin wrapper over mailer

  tests/
    __init__.py
    conftest.py               # fixtures: fake providers, tmp xlsx
    test_lead_repository.py
    test_nodes.py             # nodes with fake providers
    test_graph_smoke.py       # full graph end-to-end with all-fake providers
```

Also **edit `mailer/` minimally** (see Deliverable “Draft-staging hand-off”).

---

## Requirements / dependencies

`agent/requirements.txt`:
```
langgraph>=0.2,<0.4
langchain-core>=0.3          # transitive; pin for stability
openpyxl>=3.1
pyyaml>=6.0
python-dotenv>=1.0
requests>=2.31
tenacity>=8.2                # retry/backoff for external API calls
```
Note for implementer: confirm the exact LangGraph import surface against the
installed version. The stable API used below is
`from langgraph.graph import StateGraph, START, END`. If the installed version
differs, adapt imports but keep the node/edge topology identical.

---

## Configuration files

### `agent/config.example.yaml`
```yaml
# Non-secret run configuration. Copy to config.yaml and edit.
campaign:
  keywords:                 # the "keywords array"
    - "solar energy forecasting"
    - "renewable grid analytics"
  location: "United Kingdom" # the region to target
  target_titles:            # POC job titles, priority order (from spec Module A)
    - "VP of Sales"
    - "CTO"
    - "Chief Architect"
    - "Director of Product"

limits:
  max_companies: 10         # cap discovery breadth (cost control)
  max_leads: 10             # cap rows appended per run
  per_call_delay_seconds: 1 # politeness delay between external API calls

providers:                  # which concrete adapter each stage uses
  discovery: google_cse
  contacts: proxycurl
  email_finder: hunter
  verifier: neverbounce
  copywriter: template       # switch to "claude"/"openai" once implemented

verification:
  # what to do with each NeverBounce outcome (spec Module B)
  keep_statuses: ["valid", "catchall", "unknown"]  # "invalid" is always dropped
  mark_risky_statuses: ["catchall", "unknown"]

output:
  xlsx_path: "../Quantra_Energy_Outbound_Campaign_Matrix.xlsx"  # relative to agent/
  run_drafts_after: true    # invoke Campaign-to-Drafts tool as final step
  signature_name: "[Your Name]"   # placeholder kept consistent with existing rows
  signature_title: "CPO & Founder"
```

### `agent/.env.example`
```
# Secrets only. Copy to .env (repo root .env is reused by mailer; keep keys there or in agent/.env).
GOOGLE_CSE_KEY=
GOOGLE_CSE_CX=            # the Custom Search Engine ID
PROXYCURL_API_KEY=
HUNTER_API_KEY=
NEVERBOUNCE_API_KEY=
# Only needed once copywriter is switched off "template":
# ANTHROPIC_API_KEY=
```
`loader.py` calls `dotenv.load_dotenv()` (loads root `.env`; also attempt
`agent/.env`). Secrets are read via `os.getenv`; **never** put keys in
`config.yaml`.

### `config/models.py`
```python
@dataclass(frozen=True)
class ProviderNames:
    discovery: str; contacts: str; email_finder: str; verifier: str; copywriter: str

@dataclass(frozen=True)
class AgentConfig:
    keywords: list[str]
    location: str
    target_titles: list[str]
    max_companies: int
    max_leads: int
    per_call_delay_seconds: float
    providers: ProviderNames
    keep_statuses: list[str]
    mark_risky_statuses: list[str]
    xlsx_path: str            # resolved to an absolute path in loader
    run_drafts_after: bool
    signature_name: str
    signature_title: str
```
`loader.load_config(path="agent/config.yaml") -> AgentConfig`: parse YAML,
resolve `xlsx_path` to absolute (relative to the config file dir), validate
required keys are present, raise a clear `ConfigError` listing anything missing.

---

## Domain models (`domain/models.py`)

All frozen dataclasses. These are the currency passed between nodes — vendor
JSON never leaks past a provider.

```python
@dataclass(frozen=True)
class Company:
    name: str
    domain: str            # root domain, e.g. "openclimatefix.org"
    url: str               # homepage/contact URL
    description: str = ""

@dataclass(frozen=True)
class Contact:
    full_name: str
    title: str
    linkedin_url: str = ""
    eccentricities: str = ""   # notes/quirks for the POC Details column

@dataclass(frozen=True)
class VerifiedEmail:
    address: str
    status: str            # normalized: "valid"|"catchall"|"unknown"|"invalid"
    risky: bool

@dataclass(frozen=True)
class Lead:
    company: Company
    contact: Contact
    email: VerifiedEmail
    # copy fields (filled by copywriter):
    pitch_email: str = ""
    follow_up: str = ""
    commonalities: str = ""

# The 7 xlsx columns, in file order (single source of truth for the writer):
COLUMN_ORDER = [
    "Organization URL",
    "Specific Person to Contact",
    "POC Details & Eccentricities",
    "Direct Business Email",
    "Tailored Pitch Email",
    "Follow-up Text",
    "Points of Commonality",
]
```
Provide `Lead.to_row() -> dict[str, str]` producing exactly those 7 keys,
formatting composite cells to match existing rows:
- `Organization URL` = `f"{company.name}\n{company.url}"`
- `Specific Person to Contact` = `f"{contact.full_name}\n({contact.title})"`
- `POC Details & Eccentricities` = `contact.eccentricities`
- `Direct Business Email` = `email.address`
- `Tailored Pitch Email` = `pitch_email`
- `Follow-up Text` = `follow_up`
- `Points of Commonality` = `commonalities`

---

## Provider interfaces + concrete adapters

Each `base.py` is a tiny ABC. Each concrete adapter:
- takes its API key(s) + `per_call_delay_seconds` via constructor (DI),
- wraps calls with `tenacity` retry (exponential backoff, cap ~3 attempts,
  retry only on network/5xx/429),
- logs each external call at DEBUG and failures at WARNING,
- **maps** the vendor response into our domain dataclasses,
- raises a typed `ProviderError` on unrecoverable failure (node decides whether
  to skip the item or abort).

### `discovery/base.py`
```python
class CompanyDiscoveryProvider(ABC):
    @abstractmethod
    def discover(self, keywords: list[str], location: str, limit: int) -> list[Company]: ...
```
**`google_cse.py`** — call Google Custom Search JSON API
(`https://www.googleapis.com/customsearch/v1`) with query built from
`" ".join(keywords) + " " + location`, paginate up to `limit` results, extract
title + link, derive root `domain` from the link, **dedupe by domain**, skip
obvious non-company domains (linkedin.com, facebook.com, wikipedia.org, etc. —
keep a small blocklist constant). Return `Company` list.

### `contacts/base.py`
```python
class ContactResolutionProvider(ABC):
    @abstractmethod
    def resolve(self, company: Company, target_titles: list[str]) -> Contact | None: ...
```
**`proxycurl.py`** — use Proxycurl's role/person lookup
(`/api/linkedin/company/...` + role search) to find the highest-priority person
matching `target_titles`; map name/title/linkedin_url; pull a short bio/headline
into `eccentricities`. Return `None` if nobody found (node will skip company).

### `email_finder/base.py`
```python
class EmailFinderProvider(ABC):
    @abstractmethod
    def find(self, company: Company, contact: Contact) -> str | None: ...
```
**`hunter.py`** — Hunter Email Finder
(`https://api.hunter.io/v2/email-finder`) with `domain`, `first_name`,
`last_name`. Return the email string or `None`.

### `verifier/base.py`
```python
class VerificationStatus(str, Enum):
    VALID="valid"; CATCHALL="catchall"; UNKNOWN="unknown"; INVALID="invalid"

class EmailVerifierProvider(ABC):
    @abstractmethod
    def verify(self, email: str) -> VerificationStatus: ...
```
**`neverbounce.py`** — NeverBounce single-check
(`https://api.neverbounce.com/v4/single/check`); map their result
(`valid`/`invalid`/`catchall`/`unknown`/`disposable`) into `VerificationStatus`
(treat `disposable`/`accept_all`→ per closest bucket). Node applies
`keep_statuses` / `mark_risky_statuses` from config.

### `copywriter/base.py`
```python
@dataclass(frozen=True)
class CopyOutput:
    pitch_email: str; follow_up: str; commonalities: str

class CopywriterProvider(ABC):
    @abstractmethod
    def write(self, company: Company, contact: Contact, config: AgentConfig) -> CopyOutput: ...
```
**`template_stub.py`** — `TemplateCopywriter` builds the three text blocks
deterministically from the company/contact fields, matching the **style and
structure of the existing rows** in the workbook (greeting to `contact.full_name`,
three "Potential synergies" bullets referencing `company.name`, the standard
Quantra value paragraph, CTA, and the `signature_name`/`signature_title`
signature; a shorter follow-up; a 3-bullet commonalities block). Include a
prominent `# TODO(copywriter): replace with LLM adapter` and a docstring
pointing at `system_specification.md` Module C's negative-constraint prompt
directives so the future Claude/OpenAI adapter honors them.

### Registries (`__init__.py` in each provider dir)
Each exposes `get_<capability>(name: str, secrets, delay) -> Provider` with a
`{name: class}` dict, raising a clear error listing available names — copy the
shape of `mailer/drafts/__init__.py`.

### `providers/bundle.py`
```python
@dataclass(frozen=True)
class ProviderBundle:
    discovery: CompanyDiscoveryProvider
    contacts: ContactResolutionProvider
    email_finder: EmailFinderProvider
    verifier: EmailVerifierProvider
    copywriter: CopywriterProvider

def build_providers(config: AgentConfig) -> ProviderBundle:
    # reads keys via os.getenv, calls each get_* factory, returns the bundle
```

---

## Observability

### `observability/logging_setup.py`
`configure_logging(run_id: str) -> logging.Logger`:
- root/`agent` logger at INFO (DEBUG if `AGENT_DEBUG=1`),
- **two handlers**: `StreamHandler` (console) + `FileHandler`
  `agent/logs/agent_run_<run_id>.log`,
- format: `%(asctime)s %(levelname)s %(name)s [%(step)s]: %(message)s` — use a
  `logging.Filter`/`LoggerAdapter` to inject the current `step` (default `-`).
- `run_id` = `datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")`.

### `observability/step_logger.py`
- `@logged_step("discover_companies")` decorator wrapping each node fn: logs
  `START`, then on return logs `OK` with a one-line summary (counts) or `FAIL`
  with the exception, records a `StepRecord(step, status, detail, duration_ms)`,
  appends it to `state["step_log"]`, and re-raises only on abort-level errors.
- This satisfies "logs all the steps performed and the status of the step."

---

## LangGraph wiring

### `graph/state.py`
```python
import operator
from typing import Annotated, TypedDict

class AgentState(TypedDict):
    # inputs (set once)
    config: AgentConfig
    run_id: str
    # working data (each node reads prior, writes next)
    companies: list[Company]
    leads: list[Lead]                       # accumulates through enrichment
    appended_row_count: int
    draft_result: dict
    # observability / control
    step_log: Annotated[list, operator.add] # reducer: nodes append records
    errors: Annotated[list, operator.add]
```
Note: `config`/`run_id`/`companies`/`leads` are last-writer-wins (each set by one
node); only `step_log` and `errors` use the `operator.add` reducer.

### `graph/nodes.py` — node contracts
Each node signature: `def node(state: AgentState) -> dict` returning only the
keys it updates. Providers/repo/logger are captured via closures from
`build_graph` (DI), **not** globals. All nodes are wrapped with `@logged_step`.

1. **`discover_companies`** → calls `bundle.discovery.discover(...)`, filters out
   domains already in the workbook via `repo.existing_domains()`, truncates to
   `max_companies`. Writes `companies`. If empty → sets an error note; router
   sends to END.
2. **`resolve_contacts`** → for each company, `bundle.contacts.resolve(...)`;
   build partial `Lead`s (company+contact) for those with a contact; drop the
   rest (logged). Writes `leads` (contact-only, email/copy empty).
3. **`find_emails`** → for each lead, `bundle.email_finder.find(...)`; drop leads
   with no email found. Updates `leads`.
4. **`verify_emails`** → `bundle.verifier.verify(...)` per lead; **branch per
   spec Module B**: drop `invalid`; keep others; set `risky` if status in
   `mark_risky_statuses`. Updates each `Lead.email`. Filter to `keep_statuses`.
5. **`generate_copy`** → `bundle.copywriter.write(...)` per surviving lead; fill
   `pitch_email`/`follow_up`/`commonalities`. Truncate to `max_leads`.
6. **`persist_rows`** → `repo.row_count()` captured as `start_row`, then
   `repo.append_leads(leads)`; write `appended_row_count` and stash `start_row`
   (put it in state or recompute) for the drafts step.
7. **`sync_drafts`** → if `config.run_drafts_after`, call
   `tools.drafts_tool.run_drafts_sync(xlsx_path=..., start_row=start_row)` and
   store `draft_result`. Else skip.

### Conditional routing
- After `discover_companies`: `route_after_discovery` → `"resolve_contacts"` if
  `companies` non-empty else `END`.
- After `verify_emails` (and `generate_copy`): if `leads` empty → `END` (nothing
  to persist). Otherwise continue.
- Use one small router function per branch point; keep them pure.

### `graph/build.py`
```python
from langgraph.graph import StateGraph, START, END

def build_graph(bundle, repo, config, logger):
    g = StateGraph(AgentState)
    g.add_node("discover_companies", make_discover(bundle, repo, logger))
    g.add_node("resolve_contacts",  make_resolve(bundle, logger))
    g.add_node("find_emails",       make_find(bundle, logger))
    g.add_node("verify_emails",     make_verify(bundle, config, logger))
    g.add_node("generate_copy",     make_copy(bundle, config, logger))
    g.add_node("persist_rows",      make_persist(repo, logger))
    g.add_node("sync_drafts",       make_sync(config, logger))

    g.add_edge(START, "discover_companies")
    g.add_conditional_edges("discover_companies", route_after_discovery,
                            {"continue": "resolve_contacts", "end": END})
    g.add_edge("resolve_contacts", "find_emails")
    g.add_edge("find_emails", "verify_emails")
    g.add_conditional_edges("verify_emails", route_after_verify,
                            {"continue": "generate_copy", "end": END})
    g.add_edge("generate_copy", "persist_rows")
    g.add_edge("persist_rows", "sync_drafts")
    g.add_edge("sync_drafts", END)
    return g.compile()
```
(`make_*` = closures injecting deps, returning the `@logged_step`-wrapped node.)

---

## Persistence (`persistence/lead_repository.py`)

`XlsxLeadRepository(xlsx_path)` — the **only** module that opens the workbook for
writing. Uses `openpyxl.load_workbook(path)` (NOT read_only) so existing rows are
preserved.
- `_header_index() -> dict[str,int]`: read row 1, map each `COLUMN_ORDER` name to
  its column index; raise `XlsxSchemaError` if any of the 7 is missing.
- `existing_domains() -> set[str]`: read the `Organization URL` column, extract
  domains from the URL line, return the set (for discovery dedupe).
- `row_count() -> int`: last populated data row number (for `start_row`).
- `append_leads(leads: list[Lead]) -> int`: for each lead, write
  `lead.to_row()` into the correct columns at `ws.max_row+1`, preserving column
  order via the header index; `wb.save(path)`; return count appended.
- Reuse the newline-composite formatting from `Lead.to_row()`. Do **not**
  reformat or touch existing rows.

Reuse note: mirror `mailer/ingestion/xlsx_reader.py`'s header-mapping approach
(`header.index(name)`) rather than assuming fixed column positions.

---

## Draft-staging hand-off (edit `mailer/`, minimal + backward-compatible)

Problem: the drafts tool reads **all** rows; running it after append would
re-draft pre-existing rows (duplicate drafts). Fix by teaching the existing tool
to optionally start from a given row — honors "use the Campaign-to-Drafts tool as
the final step" while staying idempotent.

1. `mailer/ingestion/xlsx_reader.py::read_campaign_rows(xlsx_path, start_row: int | None = None)`
   — when `start_row` is set, skip rows with `row_number < start_row`. Default
   `None` = all rows (unchanged behavior).
2. `mailer/core/campaign_runner.py::sync_campaign_to_drafts(..., start_row: int | None = None)`
   — thread `start_row` into `read_campaign_rows`. Default `None`
   (fully backward-compatible; existing callers/tests unaffected).
3. `agent/tools/drafts_tool.py::run_drafts_sync(xlsx_path, start_row)` — a thin
   adapter that adds `mailer/` to `sys.path` (like
   `mailer/scripts/save_drafts.py` does) and calls
   `sync_campaign_to_drafts(xlsx_path=xlsx_path, start_row=start_row)`, returning
   `result.as_dict()`. The agent passes the pre-append `row_count()+1` as
   `start_row` so only the newly appended rows are drafted.

Do not otherwise modify `mailer/`.

---

## CLI entry point (`agent/main.py`)

`argparse`:
- `--config PATH` (default `agent/config.yaml`)
- `--dry-run` — run discovery→copy with providers, but **skip** `persist_rows`
  writing and `sync_drafts`; just print the leads that *would* be written.
- `--max-companies N` / `--max-leads N` overrides.
- `--no-drafts` — force `run_drafts_after=False` for this run.

Flow: `load_config` → `configure_logging(run_id)` → `build_providers` →
`XlsxLeadRepository` → `build_graph` → `graph.invoke(initial_state)` → print a
JSON summary (companies found, leads persisted, `draft_result`, `errors`) and
write the same summary to the log. Exit code: 0 success, 1 config/abort error,
2 partial (some rows failed).

---

## Tests (`agent/tests/`, pytest)

- **`conftest.py`**: fake in-memory providers implementing each ABC (e.g.
  `FakeDiscovery` returns 2 seed companies), a tmp-copy of the workbook fixture.
- **`test_lead_repository.py`**: append N leads to a tmp xlsx, reopen, assert row
  count grew by N, columns landed in the right order, existing rows untouched,
  `existing_domains()` reflects both old and new.
- **`test_nodes.py`**: each node with fake providers — e.g. `verify_emails`
  drops `invalid`, marks `catchall` risky; `resolve_contacts` skips companies
  with no contact.
- **`test_graph_smoke.py`**: build the graph with an all-fake `ProviderBundle`
  and a tmp xlsx, `invoke`, assert rows appended and `step_log` contains an
  `OK` record for every stage. No network.
- Reuse `mailer/tests/` style (plain pytest, no framework fixtures needed).

---

## Verification (how to confirm it works end-to-end)

1. **Unit/smoke (no network, no keys):**
   `cd agent && pip install -r requirements.txt && python -m pytest tests/ -q`
   — all green, graph smoke test appends to a tmp workbook.
2. **Dry run with real providers (needs API keys in `.env`, but writes nothing):**
   `python -m agent.main --config config.yaml --dry-run --max-companies 1`
   — logs each step to console + `agent/logs/agent_run_*.log`; prints the single
   lead it *would* append; confirms discovery→contact→email→verify→copy all
   return real data.
3. **Live single-lead run:**
   `python -m agent.main --max-companies 1 --max-leads 1`
   — one new row appended to `Quantra_Energy_Outbound_Campaign_Matrix.xlsx`; then
   the drafts tool drafts **only that new row** (verify in mailbox Drafts, and
   that pre-existing rows were not re-drafted). Inspect the log file for a full
   step trace with statuses.
4. **Regression:** `cd mailer && python -m pytest tests/ -q` and
   `python scripts/save_drafts.py --dry-run` still pass (the `start_row` param is
   backward-compatible).

---

## Out of scope (explicitly not in this pass)
- Modules D/E/G (Postgres, Google Sheet mirror, Kanban dashboard, cron
  follow-ups). Only A→B→C + persistence + draft staging.
- A real LLM copywriter adapter (interface + template stub only; wiring
  Claude/OpenAI is a later drop-in — see `copywriter/base.py`).
- Async/worker-queue execution; this pass runs synchronously per invocation.

## Post-implementation bookkeeping
Update `memory.md`, `apgent.md`, and `Claude.md` with the new `agent/` package,
the provider stack, the `mailer/` `start_row` addition, and the "copywriter LLM
still TODO" status.
