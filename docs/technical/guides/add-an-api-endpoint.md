---
type: how-to
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Add an API endpoint

1. **The service first.** Put the use case in the right `outbound/services/` module, with its refusals (`LeadError`, `InvalidInput`, …) and its events, and test it in `tests/db/`. The router stays thin.
2. **Models:** add `…In` (extends `In`: `extra="forbid"`, length limits, `Field` ranges) and `…Out` (extends `Out`) to `outbound/api/schemas.py`. Prefer a named response model to a `dict` (see [R-18](../tech-debt-and-risks.md#r-18--p3--api-the-openapi-document-is-incomplete)).
3. **The route:** add it in the right `outbound/api/routers/*.py`.
   - The router's guard (login + CSRF) applies automatically.
   - Take `row_version` for edits to a lead or message.
   - Return 201 for creation, 202 for queued work, 204 for no body.
   - Never run the pipeline in a request: queue a run.
   - Use `def`, not `async def`, unless the handler awaits something; blocking work then runs in the thread pool.
4. **Errors** come from the exception mapping in `outbound/api/errors.py`. Raise domain errors, not `HTTPException`. A new stable code needs a row in [API conventions](../api/api-conventions.md#errors).
5. **Tests:** `tests/api/test_endpoints.py`, covering the happy path, each refusal, auth (anonymous refused), and the 409 on a stale version.
6. **Regenerate the client and commit it:** `cd web2 && npm run gen:api` (writes `openapi.json` and `src/api/schema.ts`). CI fails if you forget.
7. **Docs:** [API reference](../api/api-reference.md) (and the operation count), the [API LLD](../lld/api.md) router table, and the services LLD.
8. **The CLI**, if the operator needs it from the terminal: add a command in `outbound/cli/` that calls the same service, update the [CLI page](../lld/cli.md), and test it in `tests/test_cli.py`.
