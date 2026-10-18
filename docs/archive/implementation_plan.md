# Sender Profile + Generic LLM Copywriter — Implementation Plan (v3)

> **v3 changes vs v2:** removed the multi-endpoint `llm_endpoints` registry (one
> LLM task exists → one flat `llm:` block), removed the `str | LlmTaskConfig`
> union type (copywriter stays a plain string), removed redundant registry
> aliases, fixed a banned phrase in the current template, updated the model ID,
> and rewrote every step with exact code + acceptance criteria so a smaller
> model can implement it without guessing.

---

## Problem

The agent has **zero knowledge of who is sending the emails**. The sender's
identity is hardcoded as string literals in
[template_stub.py](agent/providers/copywriter/template_stub.py) ("Quantra
Energy", "grid-intelligence mission", ...). Consequences:

1. **Commonalities are fake** — generic filler instead of genuine intersections.
2. **System is locked to Quantra** — changing the sender means editing source.
3. **An LLM copywriter can't reason** — it needs both sides of the relationship.

Bonus bug found during review: the current template pitch opens with
*"I hope this finds you well"* — explicitly banned by `system_specification.md`
Module C. Step 4 fixes this.

## Design (kept deliberately small)

```
config.yaml  sender: block ──► SenderProfile structured fields (facts)
sender_profile.md          ──► SenderProfile.narrative (free text, NOT parsed)
config.yaml  llm: block    ──► LlmConfig (one flat block — no registry)
```

- Copywriter selection stays a **plain string**: `providers.copywriter` is
  `"template"` (default, no key needed) or `"llm"`.
- The LLM adapter is **SDK-free**: one `requests.post` to an OpenAI-compatible
  `/chat/completions` endpoint. Anthropic, OpenAI, Gemini, Groq, Together, and
  Ollama all expose this interface, so switching providers = editing 2 lines of
  YAML.
- **Not building now** (removed as over-engineering; add only when a second LLM
  task exists): multi-endpoint registry, per-task endpoint assignment, union
  config types, provider-name registry aliases.

---

## Implementation Steps (do in order; each step ends with a checkable result)

### Step 1 — Config models: `SenderProfile` + `LlmConfig`

**File: [agent/config/models.py](agent/config/models.py)** — add two frozen
dataclasses (same style as the existing ones) and two fields on `AgentConfig`.
`ProviderNames` is **unchanged** (`copywriter: str` stays).

```python
@dataclass(frozen=True)
class SenderProfile:
    """Who is sending the emails. Facts come from config.yaml's sender: block;
    narrative comes verbatim from sender_profile.md (never parsed)."""
    company_name: str
    domain: str = ""
    industry: str = ""
    mission: str = ""
    value_propositions: tuple[str, ...] = ()
    technologies: tuple[str, ...] = ()
    target_verticals: tuple[str, ...] = ()
    case_studies: tuple[str, ...] = ()
    geographic_focus: str = ""
    narrative: str = ""      # raw contents of sender_profile.md


@dataclass(frozen=True)
class LlmConfig:
    """One flat LLM block. Only used when providers.copywriter == 'llm'."""
    provider: str = "anthropic"   # anthropic | openai | gemini | ollama | openai_compatible
    model: str = "claude-sonnet-5"
    base_url: str = ""            # blank = use the provider preset's default
    key_env: str = ""             # blank = use the provider preset's default
    temperature: float = 0.7
    max_tokens: int = 1200
```

On `AgentConfig` add:

```python
    sender: SenderProfile
    llm: LlmConfig
```

> Use tuples (not lists) for the repeated fields so the frozen dataclass is
> fully immutable — convert with `tuple(...)` in the loader.

**Done when:** `python -c "from agent.config.models import SenderProfile, LlmConfig"` works.

---

### Step 2 — Loader: parse `sender:`, `sender_profile.md`, `llm:`

**File: [agent/config/loader.py](agent/config/loader.py)** — inside
`load_config()`, after the existing `output` parsing, add:

```python
    # --- sender profile ------------------------------------------------------
    sender_raw = raw.get("sender", {})
    company_name = _get(sender_raw, "company_name", required=True) or ""

    profile_rel = _get(sender_raw, "profile_path", required=False, default="sender_profile.md")
    profile_file = config_path.parent / profile_rel
    narrative = profile_file.read_text(encoding="utf-8") if profile_file.exists() else ""

    sender = SenderProfile(
        company_name=str(company_name),
        domain=str(_get(sender_raw, "domain", required=False, default="")),
        industry=str(_get(sender_raw, "industry", required=False, default="")),
        mission=str(_get(sender_raw, "mission", required=False, default="")),
        value_propositions=tuple(_get(sender_raw, "value_propositions", required=False, default=[]) or []),
        technologies=tuple(_get(sender_raw, "technologies", required=False, default=[]) or []),
        target_verticals=tuple(_get(sender_raw, "target_verticals", required=False, default=[]) or []),
        case_studies=tuple(_get(sender_raw, "case_studies", required=False, default=[]) or []),
        geographic_focus=str(_get(sender_raw, "geographic_focus", required=False, default="")),
        narrative=narrative,
    )

    # --- llm block (only matters when providers.copywriter == "llm") ---------
    llm_raw = raw.get("llm", {})
    llm = LlmConfig(
        provider=str(llm_raw.get("provider", "anthropic")),
        model=str(llm_raw.get("model", "claude-sonnet-5")),
        base_url=str(llm_raw.get("base_url", "")),
        key_env=str(llm_raw.get("key_env", "")),
        temperature=float(llm_raw.get("temperature", 0.7)),
        max_tokens=int(llm_raw.get("max_tokens", 1200)),
    )
```

Then pass `sender=sender, llm=llm` in the final `AgentConfig(...)` call, and add
these validations before it (after the `missing` check):

```python
    if provider_names.copywriter not in ("template", "llm"):
        raise ConfigError(
            f"providers.copywriter must be 'template' or 'llm', got {provider_names.copywriter!r}"
        )
    if provider_names.copywriter == "llm" and not sender.narrative:
        raise ConfigError(
            f"providers.copywriter is 'llm' but {profile_file} is missing or empty. "
            "Create sender_profile.md next to config.yaml (see sender_profile.example.md)."
        )
```

Also update the imports: `from .models import AgentConfig, ConfigError, LlmConfig, ProviderNames, SenderProfile`.

**Done when:** loading a config with a `sender:` block containing only
`company_name` succeeds; setting `copywriter: llm` without a
`sender_profile.md` raises a clear `ConfigError`.

---

### Step 3 — Config + profile templates

**File: [agent/config.example.yaml](agent/config.example.yaml)** — append
(and mirror into the user's real `agent/config.yaml` if it exists):

```yaml
# -----------------------------------------------------------------------------
# Who is sending the emails. Only company_name is required.
# Rich narrative goes in sender_profile.md (see profile_path).
# -----------------------------------------------------------------------------
sender:
  company_name: "Quantra Energy"
  domain: "quantraenergy.com"
  industry: "Energy & Renewables Analytics"
  mission: "AI-driven intelligence for energy-sector decision-making"
  value_propositions:
    - "Renewable grid analytics — slots into workflows, cuts integration from months to days"
    - "Energy-forecast error reduction of 20–35%, improving trading desk P&L"
  technologies:
    - "machine learning"
    - "renewable forecasting"
    - "grid optimization"
    - "dispatch algorithms"
  target_verticals: ["Grid operators", "Energy trading desks"]
  case_studies:
    - "Reduced forecast error 30% for a UK energy trader — £2M annual P&L uplift"
  geographic_focus: "UK, Europe, India"
  profile_path: "sender_profile.md"   # relative to config.yaml

# -----------------------------------------------------------------------------
# LLM used by the copywriter when providers.copywriter is "llm".
# provider presets: anthropic | openai | gemini | ollama | openai_compatible
# For openai_compatible (Groq, Together, ...) also set base_url and key_env.
# -----------------------------------------------------------------------------
llm:
  provider: "anthropic"
  model: "claude-sonnet-5"
  temperature: 0.7
  max_tokens: 1200
  # base_url: "https://api.groq.com/openai/v1"   # openai_compatible only
  # key_env: "GROQ_API_KEY"                       # openai_compatible only
```

And change the providers block comment:

```yaml
providers:
  # ...existing four unchanged...
  copywriter: template      # "template" (no API key) or "llm" (uses llm: block below)
```

**File: [agent/sender_profile.example.md](agent/sender_profile.example.md)** — NEW.
Section skeleton only; the human fills it in and saves as `sender_profile.md`:

```markdown
# <Company> — Sender Profile

## Who We Are
<2-3 paragraphs: company, founding story, mission>

## What We Do
<core product and how it works>

## Key Differentiators
- <what makes you different>

## Proof Points / Case Studies
- <quantified outcome>

## Technology & Overlap Keywords
<keywords for finding genuine intersections with targets: e.g. machine
learning, grid optimization, renewable forecasting, ...>

## Target Customers & Why They Buy
<who buys, what problem they have, why you>
```

**File: [agent/.env.example](agent/.env.example)** — append:

```bash
# --- LLM copywriter (only needed when providers.copywriter is "llm") ---------
# Set the ONE key matching llm.provider in config.yaml:
ANTHROPIC_API_KEY=
# OPENAI_API_KEY=
# GEMINI_API_KEY=
# (openai_compatible providers use the var named by llm.key_env)
```

**Done when:** the three template files exist and `config.example.yaml` parses
(`python -c "import yaml; yaml.safe_load(open('agent/config.example.yaml'))"`).

---

### Step 4 — De-hardcode the template copywriter (+ fix banned phrase)

**File: [agent/providers/copywriter/template_stub.py](agent/providers/copywriter/template_stub.py)**

Rules:
1. Replace every literal `"Quantra Energy"` / Quantra-specific claim with
   `config.sender.*` fields (`s = config.sender` at the top of `write()`).
2. **Delete the line "I hope this finds you well."** — banned by Module C. Open
   directly with the hook instead.
3. Synergy bullets: use the first 2 entries of `s.value_propositions` (fall back
   to a neutral sentence when empty) plus one bullet combining `company.name` +
   `s.company_name`.
4. Commonalities via **exact word-overlap, nothing fancier**:

```python
def _matching_technologies(technologies: tuple[str, ...], description: str) -> list[str]:
    """Case-insensitive: keep a technology if any of its words (len>3) appears
    in the company description."""
    desc = description.lower()
    hits = []
    for tech in technologies:
        words = [w for w in tech.lower().split() if len(w) > 3]
        if any(w in desc for w in words):
            hits.append(tech)
    return hits
```

   Bullets = up to 2 matched technologies ("Shared focus on <tech>") + one
   `industry`/mission alignment bullet. When nothing matches, fall back to the
   current generic bullets but built from `s.industry` / `s.mission`.

**Done when:** `grep -ri "quantra\|hope this finds" agent/providers/copywriter/template_stub.py`
returns nothing, and existing tests still pass.

---

### Step 5 — `LlmCopywriter` (SDK-free, one class)

**File: [agent/providers/copywriter/llm_copywriter.py](agent/providers/copywriter/llm_copywriter.py)** — NEW.

```python
_PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "anthropic":         {"base_url": "https://api.anthropic.com/v1", "key_env": "ANTHROPIC_API_KEY"},
    "openai":            {"base_url": "https://api.openai.com/v1", "key_env": "OPENAI_API_KEY"},
    "gemini":            {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "key_env": "GEMINI_API_KEY"},
    "ollama":            {"base_url": "http://localhost:11434/v1", "key_env": ""},
    "openai_compatible": {"base_url": "", "key_env": "LLM_API_KEY"},
}
```

Class contract (mirror the retry/log style of
[hunter.py](agent/providers/email_finder/hunter.py)):

- `__init__(self, llm: LlmConfig, sender: SenderProfile, per_call_delay_seconds: float = 1.0)`
  — resolve `base_url` = `llm.base_url or preset["base_url"]` (raise
  `ProviderError` if still blank), `key_env` = `llm.key_env or preset["key_env"]`,
  `api_key = os.getenv(key_env, "")` (raise `ProviderError` naming the missing
  env var, unless `key_env` is blank as for ollama). Unknown `llm.provider` →
  `ProviderError` listing valid presets.
- `write(self, company, contact, config) -> CopyOutput`:
  1. Build messages (prompt below).
  2. `POST {base_url}/chat/completions` via `requests` with
     `{"model": llm.model, "messages": [...], "temperature": ..., "max_tokens": ...}`,
     header `Authorization: Bearer {api_key}` (omit when no key), timeout 60s.
  3. Wrap with the same `tenacity` retry decorator pattern used by the other
     providers (3 attempts, expo backoff, retry only on `requests` errors /
     429 / 5xx).
  4. Parse `resp.json()["choices"][0]["message"]["content"]` → JSON → `CopyOutput`.

**JSON parsing must be defensive** (models wrap JSON in fences):

```python
def _parse_copy_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]          # drop opening fence
        text = text.removeprefix("json").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ProviderError(f"LLM response contained no JSON object: {text[:200]!r}")
    return json.loads(text[start : end + 1])
```

Map: `pitch_email` (str), `follow_up` (str), `commonalities` — if the model
returns a list, join as `"\n".join(f"• {c}" for c in value)` to match the
existing column format; if a string, use as-is. Missing key → `ProviderError`.

**System prompt** (single string constant `_SYSTEM_PROMPT`):

```
You are a world-class executive salesperson writing brief, human-sounding
outbound emails.

BANNED PHRASES (never write any of these): "I hope this email finds you well",
"I hope this finds you well", "In today's fast-paced", "revolutionary",
"delighted to connect", "synergy", "leverage", "cutting-edge", "game-changer",
"I wanted to reach out", "touch base".

STRUCTURE RULES:
- pitch_email: max 150 words. One singular, low-friction call to action.
- The first 2 sentences must hook on the contact's specific background.
- Sentences 3-5 tie the sender's capabilities to the target's actual work.
- Sign off exactly with:\n{signature_name}\n{signature_title}
- follow_up: shorter than the pitch; references the prior email.
- commonalities: exactly 3 bullets of GENUINE intersections between the
  sender's real capabilities and the target's real work. Never generic filler.

Respond ONLY with a JSON object:
{"pitch_email": "...", "follow_up": "...", "commonalities": ["...", "...", "..."]}
```

**User message** (f-string): sender narrative verbatim, then value_propositions
and technologies as bullets, then target company name/description, then contact
name/title/eccentricities, then signature name/title values.

**Done when:** the class imports cleanly and `test_llm_copywriter.py` (Step 7)
passes with `requests.post` mocked.

---

### Step 6 — Registry + bundle wiring (2 small edits)

**File: [agent/providers/copywriter/__init__.py](agent/providers/copywriter/__init__.py)**

```python
from .llm_copywriter import LlmCopywriter

_REGISTRY = {
    "template": TemplateCopywriter,
    "llm":      LlmCopywriter,
}

def get_copywriter(name: str, **kwargs) -> CopywriterProvider:
    cls = _REGISTRY.get(name)
    if cls is None:
        raise ProviderError(f"Unknown copywriter {name!r}. Available: {list(_REGISTRY)}")
    if cls is LlmCopywriter:
        return LlmCopywriter(
            llm=kwargs["llm"], sender=kwargs["sender"],
            per_call_delay_seconds=kwargs.get("per_call_delay_seconds", 1.0),
        )
    return cls()
```

(No `"claude"`/`"openai"` aliases — the provider is chosen in `llm.provider`.)

**File: [agent/providers/bundle.py](agent/providers/bundle.py)** — change one call:

```python
    copywriter = get_copywriter(
        pnames.copywriter,
        llm=config.llm,
        sender=config.sender,
        per_call_delay_seconds=delay,
    )
```

**Done when:** `copywriter: template` builds with no keys set;
`copywriter: llm` with `ANTHROPIC_API_KEY` unset raises a `ProviderError` that
names the missing variable.

---

### Step 7 — Tests

**File: [agent/tests/conftest.py](agent/tests/conftest.py)** — the shared
`test_config` fixture gains `sender=SenderProfile(company_name="TestCo",
technologies=("machine learning", "forecasting"), narrative="TestCo builds ML
forecasting tools.")` and `llm=LlmConfig()`. This is the only conftest change;
every existing fixture keeps working because both new `AgentConfig` fields are
supplied here.

**File: [agent/tests/test_llm_copywriter.py](agent/tests/test_llm_copywriter.py)** — NEW,
mock `requests.post` (`unittest.mock.patch`). Cases:

1. Happy path: mocked 200 with a JSON body → `CopyOutput` fields populated;
   list-form commonalities joined into `• `-prefixed lines.
2. Prompt contains `sender.narrative`, each technology, and
   `contact.eccentricities` (inspect the mocked call's `json=` payload).
3. Fenced response (` ```json ... ``` `) parses correctly.
4. Missing `pitch_email` key → `ProviderError`.
5. Missing API key env var → `ProviderError` naming the variable.
6. Unknown `llm.provider` → `ProviderError`.

**File: [agent/tests/test_template_copywriter.py](agent/tests/test_template_copywriter.py)** — NEW (or extend `test_nodes.py`):

1. Output contains `sender.company_name`, not the literal "Quantra".
2. Output contains no banned phrase ("hope this finds", "I wanted to reach out").
3. `_matching_technologies(("machine learning",), "We do machine learning")` →
   `["machine learning"]`; no match → fallback bullets still non-empty.

**Loader tests** (extend existing config tests): sender block with only
`company_name` loads; `copywriter: llm` without profile file raises
`ConfigError`; `llm:` block absent → defaults applied.

**Done when:** `python -m pytest agent/tests/ -q` — all 22 existing tests plus
the new ones pass, zero network.

---

### Step 8 — Docs + bookkeeping

- `agent/README.md`: add a "Sender profile & LLM copywriter" section — the two
  files to create (`config.yaml` sender/llm blocks, `sender_profile.md`), the
  one env key to set, and the one-line switch `copywriter: llm`.
- Update `memory.md`, `apgent.md`, `Claude.md`: registry idea replaced by flat
  `llm:` block (one task → one block; registry deferred), template de-hardcoded,
  `LlmCopywriter` shipped.

---

## Verification Plan

```bash
# 1. Full suite (no network, no keys)
source .venv/bin/activate && python -m pytest agent/tests/ -q

# 2. Template path still works end-to-end, now de-hardcoded
python -m agent.main --dry-run --max-companies 1 --no-drafts
#    → pitch shows sender.company_name from config, no "hope this finds you well"

# 3. LLM path (needs ANTHROPIC_API_KEY in .env; set copywriter: llm in config.yaml)
python -m agent.main --dry-run --max-companies 1 --no-drafts
#    → commonalities are specific intersections, ≤150-word pitch, correct signature

# 4. Misconfiguration UX (should fail with clear, named errors)
#    a) copywriter: llm + no sender_profile.md      → ConfigError mentioning the file
#    b) copywriter: llm + missing ANTHROPIC_API_KEY → ProviderError naming the var
```

**Quality bar for step 3:** commonalities read like the hand-written WattTime
row (specific overlapping technical themes), not generic filler.

## What the user must supply before the LLM path works
1. Fill `sender:` block in `agent/config.yaml` (only `company_name` required;
   the more fields, the better the copy).
2. Write `agent/sender_profile.md` (copy `sender_profile.example.md`).
3. Put one API key in `.env` (e.g. `ANTHROPIC_API_KEY=`).
4. Flip `providers.copywriter` to `llm`.
