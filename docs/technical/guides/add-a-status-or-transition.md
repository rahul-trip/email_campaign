---
type: how-to
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Add a status or a transition

Statuses and their transitions are a contract between code, database, UI and docs. Change them together.

**A new transition between existing statuses:**

1. Add the target to the source's row in the right table in `outbound/domain/state_machines.py`, with a comment saying who makes that move.
2. Make the move only through the repository's `transition(...)`, so it is checked and writes its event.
3. Test it in `tests/domain/test_state_machines.py` (the table) and where it is used (`tests/db/...`).
4. Update [state machines](../hld/state-machines.md) (diagram and table) and [PLAN.md §7](../../PLAN.md#7-lifecycles) if it changes the product's lifecycle.

**A new status value:**

1. Add it to the `StrEnum` in `outbound/domain/enums.py`.
2. Give it a row in its transition table. The module refuses to import otherwise. Add it to the rows that may reach it.
3. **Write a migration** that widens the matching `CHECK` constraint by name (see `0003_unconfirmed_contacts.py`), following the [migration rules](../data/migrations.md). The downgrade must refuse while rows use the new value.
4. If it is a company status, decide whether it is a stage's input (`STAGE_INPUT_STATUS`), a hold resume point, or final.
5. Add its label and family to `web2/src/lib/status.ts`. The UI falls back to a humanised label, but give it a proper one.
6. Tests:
   - the state table;
   - `tests/db/test_migrations.py`, which checks that `CHECK` lists equal the enums;
   - where it is used.
7. Docs: [state machines](../hld/state-machines.md), [schema](../data/schema.md), the [manual](../../USER_MANUAL.md) if the operator sees it, and the [glossary](../glossary.md) if it is a new idea.
