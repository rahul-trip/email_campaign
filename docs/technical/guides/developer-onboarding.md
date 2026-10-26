---
type: tutorial
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Developer onboarding

From a clean clone to green tests and a working app on your machine, **without any vendor key and without spending anything**. It takes about 30 minutes. You will finish by running the pipeline end to end against a fake outside world.

## 1. Tools

- [uv](https://docs.astral.sh/uv/). It installs Python 3.12 for you (`.python-version`).
- Node 22 and npm, for the web app.
- git.
- **Not needed:** Docker (only for the deploy rehearsal) and Postgres (tests can start a throwaway one).

## 2. Get the code and the environment

```bash
git clone https://github.com/rahul-trip/email_campaign.git && cd email_campaign
uv sync                              # builds .venv with dev tools (and the legacy group)
uv run pre-commit install            # ruff, mypy, gitleaks and the layer check on every commit
```

## 3. Read the rules (10 minutes)

1. [CLAUDE.md](../../../CLAUDE.md): the binding rules. Every change follows them.
2. [Architecture](../architecture/architecture.md) §1–§5, and the [HLD](../hld/hld.md) §1–§4.
3. The [safety model](../hld/safety-model.md). Everything here exists to keep it true.

## 4. Run the checks

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run lint-imports
uv run pytest                        # about 1,560 tests on SQLite, no network
```

All green? You have a working environment. Optional: the same suite on a throwaway Postgres, still without Docker:

```bash
uv run --with pgserver python -m scripts.pg_tests tests -q
```

## 5. Run the app against fake vendors

In one terminal:

```bash
(cd web2 && npm ci && npm run build)
uv run python -m scripts.e2e_server        # the real API + worker, fake vendors, on :8765
```

Open <http://127.0.0.1:8765> and sign in with `e2e-password-123`. The guided tour starts. Then:

1. **Add leads:** add `example.com` by website.
2. **Runs:** start a run. The worker researches, gates, finds an address and writes an email, all with fakes and at no cost.
3. **Review:** read the email. Approve it, then start another run: the fake mailbox gets the draft.
4. Open the lead, then its **Journey**, and see each stage, its events and its (fake) vendor calls.

To work on screens with live reload, run `cd web2 && API_TARGET=http://127.0.0.1:8765 npm run dev` and open <http://127.0.0.1:5174>.

## 6. Run the browser tests

```bash
cd web2 && npx playwright install chromium && npx playwright test
```

## 7. Find your way around the code

| Want to understand… | Start at |
|---|---|
| How a lead moves | `outbound/runner/runner.py::Runner._process` |
| A stage | `outbound/stages/<stage>`, then its [LLD](../README.md#low-level-design) |
| What a status means | `outbound/domain/state_machines.py`, [state machines](../hld/state-machines.md) |
| How a screen gets its data | `web2/src/pages/<Page>.tsx`, then `outbound/api/routers/`, then `outbound/services/` |
| How money is counted | `outbound/metering/metered.py::Meter.call` |
| How it is wired | `outbound/pipeline.py::assemble` |

## 8. Make your first change

1. Branch: `git switch -c phase-3b/<task>`.
2. Write the failing test first, at the lowest layer that proves it ([testing strategy](../quality/testing-strategy.md)).
3. Change the code; keep the [definition of done](../quality/definition-of-done.md).
4. Update the docs the change touches (the PR template lists them).
5. Push and open a pull request; CI must be green.

## Running with real vendors (later)

Copy `.env.example` to `.env` and fill it in (see the [configuration reference](../operations/configuration-reference.md)). Then `uv run outbound db upgrade && uv run outbound seed`, `uv run outbound serve`, and `uv run outbound worker`.

**Real keys spend real money and save real drafts.** Check them first with `uv run python -m scripts.live_check`, which uses only your own address.
