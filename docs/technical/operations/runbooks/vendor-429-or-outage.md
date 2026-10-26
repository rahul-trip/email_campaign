---
type: how-to
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# A vendor is failing or rate-limiting

| | |
|---|---|
| **Severity** | SEV-3 (SEV-2 if every lead fails) |
| **Impact** | Leads fail at research (Tavily or the LLM) or the email step (finders and verifiers), or come back unproven. |
| **Signals** | `provider_retry` WARNINGs; `provider_call` with `outcome: error`; leads `failed` with a provider name in `last_error`; `ProviderAuthError` (401/403) |
| **Related** | [integrations](../../integrations/README.md), [providers](../../lld/providers.md) |

On the VM, set up the usual alias first:

```bash
cd /opt/outbound/current && export RELEASE=$(basename "$(readlink /opt/outbound/current)")
alias oc='docker compose -p outbound -f deploy/compose.yml'
```

## 1. Confirm

```bash
oc logs --since 2h worker | grep -E '"provider_retry"|"outcome": "error"' | tail -20
```
```sql
SELECT provider, outcome, count(*) FROM provider_calls
WHERE workspace_id = :ws AND created_at > now() - interval '2 hours' GROUP BY 1, 2;
```

| Pattern | Meaning |
|---|---|
| 401 or 403, `ProviderAuthError` | A key is wrong, expired or out of credit. Not retried |
| 429 with retries | Rate limiting. Retried up to 3 times, honouring `Retry-After` up to 60 s |
| 5xx or timeouts | Vendor outage |
| `the reply was cut off at the token limit` | Raise `LLM_MAX_TOKENS` |

## 2. Contain

Pause runs if every lead is failing, so the back-off does not use up the 3 automatic attempts.

## 3. Fix

- **Auth or credit:** fix the key or top up the account, in Doppler, then restart the worker.
- **A finder or verifier is down:** take it out of `FINDER_CHAIN` (or switch `VERIFIER`) in Doppler and restart. The waterfall uses what remains.
- **Tavily or the LLM is down:** wait. Failed leads retry with back-off (if `tick` runs), or use **Retry** on the lead page once the vendor is back.

## 4. Verify

New leads advance; `provider_call` outcomes are `hit` or `miss` again.

## 5. Follow up

If a vendor keeps failing, revisit the chain with the bake-off ([integrations](../../integrations/README.md#choosing-and-changing-the-chain)).
