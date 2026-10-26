---
type: how-to
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Write a data-fix script

For correcting live data after a bug. The rules and the production procedure are in [data fixes](../operations/data-fixes.md); this guide is the writing part. `scripts/fix_discovery_data.py` is the worked example.

1. **Fix the cause first**, in its own change, so the data does not go wrong again.
2. **Create `scripts/fix_<what>.py`** with the [header template](../_templates/data-fix-script.md): what it fixes, why, how to run it, and the rules it follows.
3. **Structure it as a plan of actions.** `plan(factory, ws, …) -> list[Action]` looks up each target by a stable key (domain, then name) and returns an `Action(what, apply)` only if there is something left to do. `main()` prints the plan, and applies it only with `--apply`.
4. **Change data only through services or repositories**, never raw SQL, so events, state machines and refusals apply. Use `SYSTEM` as the actor for engine corrections, and `OPERATOR` for changes the operator asked for.
5. **Put paid work behind its own flag** (for example `--rerun-research`), and say the cost in the help text.
6. **Test it** in `tests/db/test_fix_<what>.py` on a seeded copy of the situation: the plan lists the expected actions; applying it gives the expected data and events; a second plan is empty.
7. **Review and run it** as described in [data fixes](../operations/data-fixes.md#running-one-in-production).
