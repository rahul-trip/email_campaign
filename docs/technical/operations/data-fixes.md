---
type: how-to
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# One-off data fixes

Sometimes live data has to be corrected after a bug, for example the first discovery run's headline names and mismatched people (Phase 3b 3b.16). A data fix changes the business record and the audit trail, so it follows the same rules as the engine. `scripts/fix_discovery_data.py` is the reference example.

## Rules

A data-fix script MUST:

1. **Change nothing by default.** It prints its plan. Only `--apply` makes changes.
2. **Go through services or repositories, never raw SQL**, so every change writes the same events, checks the same state machines and honours the same refusals as the app.
3. **Be idempotent.** Each step finds its target by a stable key (domain, then name) and skips itself once done. Running it twice changes nothing the second time.
4. **Be scoped** to one workspace (`--workspace`, default `default`).
5. **Act as the right actor.** Engine corrections are written as `SYSTEM`, so they are not marked as operator input. Changes made on the operator's behalf use `OPERATOR`.
6. **Have a test** on a seeded copy of the data, proving the plan, the result, and an empty plan on a second run (`tests/db/test_fix_discovery_data.py`).
7. **Keep personal data out of logs.** The printed plan may name people and domains, because the operator must check it, but it is printed to the terminal only.
8. **Start with the header** from [the template](../_templates/data-fix-script.md), saying what it fixes and why.

Paid vendor calls (re-running research) MUST be behind their own flag (`--rerun-research`) and say what they cost.

## Running one in production

1. Review the PR: the plan, the test, and the steps it will take.
2. Deploy the commit that contains the script, plus the fixes for the cause, so the data does not go wrong again.
3. Print the plan. The image does not contain `scripts/` (`.dockerignore`), so run the script from a trusted machine with a checkout of the deployed commit, pointed at production. This needs a Doppler login that can read `outbound/prd`:

   ```bash
   git checkout <deployed sha>
   # Doppler injects POSTGRES_URL and the other secrets, so nothing is pasted or written down.
   DATABASE_BACKEND=postgres doppler run --project outbound --config prd -- \
     uv run python -m scripts.fix_discovery_data            # the plan
   DATABASE_BACKEND=postgres doppler run --project outbound --config prd -- \
     uv run python -m scripts.fix_discovery_data --apply    # do it
   ```

   This counts as one more database client ([capacity](capacity-and-limits.md#database-connections)). Alternatively, mount the script into a one-off container (`oc run --rm --no-deps -v "$PWD/scripts:/app/scripts:ro" api python -m scripts.<name>`). That is untested; rehearse it first.

4. Check the plan against the operator's understanding, then run it with `--apply`.
5. Run it again without `--apply`. It must print "Nothing to do".
6. Spot-check the timeline of a changed lead: the events show what changed and who changed it.

## When a script is not enough

A fix the services cannot express (a schema change, a bulk rewrite of JSON) is a migration, not a script ([migrations](../data/migrations.md)). A fix to a single lead belongs in the app, through the lead page.

## How to refresh this page

```bash
sed -n '1,25p' scripts/fix_discovery_data.py
grep -n "scripts" .dockerignore
```
