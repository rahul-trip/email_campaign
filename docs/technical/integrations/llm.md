---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# LLM

| | |
|---|---|
| **Role** | Every model call: research (site facts, signals, persona, fit) and copy (writer, critic) |
| **Port** | `LlmClient` |
| **Adapter** | `outbound/providers/adapters/llm.py::OpenAiCompatibleLlm`, one adapter for any OpenAI-compatible chat-completions endpoint |
| **Registry** | `build_llm`: `LLM_PROVIDER` picks a preset |
| **Settings** | `LLM_PROVIDER`, `LLM_MODEL`, `LLM_BASE_URL`, `LLM_TEMPERATURE` (0.7), `LLM_MAX_TOKENS` (4,000); the key from the provider's own variable, else `LLM_API_KEY` |
| **Price** | `LLM_PRICES` per model, `(input, output)` per million tokens. **No defaults**, so calls are recorded at $0 until set ([R-03](../tech-debt-and-risks.md#r-03--p1--cost-model-calls-are-recorded-at-0-b5)) |
| **Cache** | None by default (identical prompts should give different drafts) |
| **Status** | Live-checked 2026-10-19 |

## Presets

| `LLM_PROVIDER` | Base URL | Key variable | JSON mode |
|---|---|---|---|
| `anthropic` (default; model `claude-sonnet-5-5`) | `https://api.anthropic.com/v1` | `ANTHROPIC_API_KEY` | No: the prompt asks for JSON |
| `openai` | `https://api.openai.com/v1` | `OPENAI_API_KEY` | Yes |
| `gemini` | `https://generativelanguage.googleapis.com/v1beta/openai` | `GEMINI_API_KEY` | Yes |
| `github_copilot` | `https://api.githubcopilot.com` (with the editor headers it requires) | `COPILOT_API_KEY` | No |
| `ollama` | `http://localhost:11434/v1` | none | Yes |
| `openai_compatible` (OpenRouter, Groq, Together, …) | `LLM_BASE_URL` (required) | `LLM_API_KEY` | Yes |

`LLM_BASE_URL` overrides any preset's address (for a proxy).

## Endpoints used

| Operation | Method and path | Auth | Timeout |
|---|---|---|---|
| `complete(system, user, json_mode, temperature, max_tokens)` | `POST <base>/chat/completions` with `{model, messages: [system, user], temperature, max_tokens, response_format?}` | `Authorization: Bearer <key>` | **90 s**, 3 attempts on retryable errors |

## Mapping and errors

| Answer | Result |
|---|---|
| `choices[0].message.content` and `usage.prompt_tokens` / `completion_tokens` | `LlmResult(text, model, input_tokens, output_tokens)`; missing usage counts as 0 tokens |
| `finish_reason: "length"` | `ProviderError`: "the reply was cut off at the token limit; raise LLM_MAX_TOKENS" |
| Empty text, or an unexpected shape | `ProviderError` |
| A reply that is not the expected JSON object | `ProviderError` from `outbound/providers/llm_json.py::ask_json` |

Cost is `llm_cost(LLM_PRICES, LLM_MODEL, input, output)`, rounded up to a whole micro-dollar. It is computed with the configured model name, not the model the provider reports.

## Tests and fixtures

`tests/providers/test_llm.py` (presets, headers, JSON mode, length cut-off, empty replies, usage); fixture `tests/providers/fixtures/llm/chat.json`.

## Data sent to the vendor

The provider receives:

- company page text and search snippets;
- people's names and titles found on the site;
- the operator's notes;
- the sender profile;
- the recipient's first name and title;
- previous drafts and operator edits (few-shot examples).

Check the provider's data-retention terms ([privacy](../security/privacy-data-processing.md)).
