# Phase 0 — Fix and bake-off

**Goal:** stop the live duplicate-draft bug, clean the repo, and pick the email-finding chain using real data instead of vendor claims.
**Depends on:** nothing. Runs alongside Phase 1.
**Gate:** rerunning the legacy agent creates no duplicate drafts, and the waterfall chain is chosen from bake-off numbers and written into config.

**Status (2026-10-16): code complete; the gate is waiting on two inputs only the team can supply.** Tasks 0.1 to 0.4 are done and tested. Task 0.5 is built and tested, but the bake-off itself has not run, because it needs vendor API keys and the 30 known contacts. See [To finish the gate](#to-finish-the-gate).

**Update (2026-10-18):** keys for Hunter, ZeroBounce, OrbiSearch, MyEmailVerifier, Scrubby and Tavily are now in the root `.env` (Enrichley is not subscribed, so the bake-off compares Scrubby only as the resolver). What is still missing is the list of 30 known contacts in `data/private/bakeoff_contacts.csv`.

## Scope

**In scope:**
- The bug fix in the legacy `agent/` package.
- Repo hygiene.
- The provider ports.
- The finder, verifier and catch-all resolver adapters (reused in Phase 2).
- A bake-off script.

**Out of scope:**
- Any database work (that is Phase 1).
- Anything else in `agent/` beyond the bug fix; it is retired in Phase 2.

## What changed from the plan

Reading the vendors' real API docs changed four things. All are reflected in [../PLAN.md](../PLAN.md).

1. **OrbiSearch has no finder API.** Its public API has five endpoints (verify, bulk submit, bulk status, bulk results, credits). The "finder" on its website is a web tool only. OrbiSearch is therefore a **verifier only**. Its `risky` status means an unresolved catch-all, so it can also stand in for a resolver.
2. **The finder candidates are Hunter and ZeroBounce.** ZeroBounce's finder costs **20 credits per address found**, which at $0.008 a credit is about **$0.16 per found email**. That is far above the research's "under $0.07 per prospect" figure, which assumed a cheap pay-as-you-go finder that does not exist as an API. The $0.50 ceiling still holds on those numbers, but the bake-off must test whether other API finders are cheaper. Anymail Finder and Findymail both advertise finder APIs; neither has been evaluated.
3. **Scrubby's public docs are partial.** They confirm the `x-api-key` header, `POST /add_email`, `GET /fetch_email/{email}` and a `pending` status, but not the base URL, the request body or the final result values. The adapter was written from that, and its base URL is a required setting (`SCRUBBY_BASE_URL`). **It must be confirmed with a live key.** Enrichley is documented in full and is the safe alternative.
4. **Tavily's adapter moved here from task 2.2**, so the search port has a real adapter for its contract tests. Task 2.2 no longer includes it.

Fixtures are hand-built from the vendors' documented examples, not recorded from live accounts; see `tests/providers/fixtures/README.md`. The bake-off script can record real responses to replace them.

## Tasks

### 0.1 Fix duplicate drafts in the legacy agent — done

Every run was re-drafting every existing row, because `sync_drafts` called `run_drafts_sync` without `start_row`.

- [x] `drafts_start_row` added to `AgentState`.
- [x] `make_persist` reads `row_count() + 1` before appending and returns it.
- [x] `make_sync` passes it to the mailer, and **refuses to draft** if it is missing, rather than falling back to the whole workbook.
- [x] Tests: the start-row bookkeeping, the refusal path, and a two-run test through the whole graph. The IMAP call is replaced by a recorder that reads the real workbook through the real reader. It asserts run 1 drafts rows 3 and 4, and run 2 drafts only row 5, never row 2.

**Done when:** `python -m pytest agent/ -q` is green and a second dry run drafts 0 rows. The tests cover this; a live dry run needs `agent/config.yaml` and keys, which do not exist yet.

### 0.2 Repo hygiene — done

- [x] `.venv` untracked (5,101 files). The environment is now managed by `uv` on Python 3.12, with the legacy dependencies in a `legacy` group so the old tests still run.
- [x] Root `.gitignore` written. It covers `.venv/`, `.env*` (but not `.env.example`), databases, caches, `data/private/`, `node_modules/`, `web/dist/` and logs.
- [x] `agent/.env` is not tracked and was never in git history.
- [x] No non-blank secret assignment exists in any tracked or unignored file.

### 0.3 Provider ports — done

- [x] `outbound/providers/ports.py`: `EmailFinder`, `EmailVerifier`, `CatchAllResolver` and `SearchProvider` as Protocols, with Pydantic result models. Every result carries `raw_status` (the vendor's own label) and `billed` (whether the vendor charged), because some vendors do not charge for unknown answers.
- [x] `outbound/providers/errors.py`: `ProviderError`, `ProviderAuthError`, `RateLimited`, `BudgetExceeded`. Messages never contain URLs, because several vendors take the key as a query parameter.
- [x] `outbound/providers/http.py`: one shared client for timeouts, retries on 429 and 5xx only, and error mapping. It silences httpx's own request logging, which would print URLs containing keys.
- [x] Contract suites in `tests/contract/`, one per port. Each adapter subclasses its suite and supplies its vendor's responses.

### 0.4 Adapters — done, with the caveats above

| Port | Adapters |
|---|---|
| `EmailFinder` | Hunter, ZeroBounce |
| `EmailVerifier` | Hunter, ZeroBounce, OrbiSearch, MyEmailVerifier |
| `CatchAllResolver` | Enrichley (real time), Scrubby (asynchronous, partial docs) |
| `SearchProvider` | Tavily |

- [x] Mapping rules are conservative: only an explicit valid answer is `VALID`, and anything unrecognised is `UNKNOWN`. Disposable, spam-trap and do-not-mail addresses are `INVALID`.
- [x] Hunter's key goes in a header, not the URL. A 202 from Hunter's verifier is polled until it finishes. Hunter's 451 ("person asked to stop processing") is reported as a result, not an error. Tavily's 432 and 433 become `BudgetExceeded`.
- [x] `outbound/providers/registry.py` builds adapters by name from settings; `outbound/config.py` holds the keys and the provisional chain.

### 0.5 The bake-off — built, not yet run

- [x] `scripts/bakeoff.py` with three commands:
  - `collect` runs every configured finder, verifier and resolver and saves every raw answer. It is **idempotent**: an answer already saved is never asked, or paid for, again. Bad credentials and spend caps abort the run; other errors are recorded for that cell.
  - `poll` collects answers from asynchronous resolvers.
  - `report` replays **every finder order, verifier and resolver combination** from the saved answers, offline and free, and writes `bakeoff_report.csv` plus a printed summary.
- [x] The summary also shows how each verifier treats the 30 known-good addresses. An `invalid` there is a false reject.
- [x] Metrics per chain: found, found-correct, safe, right-and-safe, wrong-but-safe (the dangerous case), held, cost per safe email, and median catch-all resolve time. Prices are in `outbound/providers/pricing.py` (`DEFAULT_PRICES`, shared with the engine's meter since Phase 2) and can be overridden with `--prices`. Scrubby's price is not public and shows as "unpriced".
- [x] `--record DIR` saves every raw vendor response (method, path, status and body only, never the query string), for replacing the hand-built fixtures.
- [ ] Run it, choose the chain, and record it. See below.

### To finish the gate

Two things only the team can supply:

1. **API keys in `.env`** (copy from [`.env.example`](../../.env.example)): at least one finder and one verifier. For a meaningful comparison, use Hunter and ZeroBounce for finding, and MyEmailVerifier, OrbiSearch and ZeroBounce for verifying, plus Enrichley and Scrubby for catch-alls. Scrubby also needs `SCRUBBY_BASE_URL` from your account.
2. **The 30 known contacts** in `data/private/bakeoff_contacts.csv` (git-ignored). Use [`data/bakeoff_contacts.example.csv`](../../data/bakeoff_contacts.example.csv) as the template.
   - Columns: `first_name, last_name, domain, country, known_email` (plus optional `full_name`).
   - At least 10 each from the US, UK and EU, and at least 5 whose domain is catch-all.

Then:

```bash
uv run python -m scripts.bakeoff collect --contacts data/private/bakeoff_contacts.csv --record data/private/recorded
uv run python -m scripts.bakeoff poll          # repeat daily until Scrubby has answered (24-72 h)
uv run python -m scripts.bakeoff report
```

Pick the winner and set `FINDER_CHAIN`, `VERIFIER` and `CATCH_ALL_RESOLVER` in `.env.example` and in the defaults in `outbound/config.py`. They are provisional now. Then review `data/private/recorded/`, remove personal data, and replace the matching fixtures under `tests/providers/fixtures/`.

## Gate record

- Date:
- Duplicate-draft check: covered by `test_graph_never_redrafts_earlier_rows`; live check:
- Bake-off summary:

| Chain | Found | Correct | Safe | Wrong-but-safe | Cost per safe email |
|---|---|---|---|---|---|
| | | | | | |

- Chosen chain:
- Scrubby adapter confirmed against a live key (yes/no, what changed):
- Checked by:
