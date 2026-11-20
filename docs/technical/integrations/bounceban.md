---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-11-20 (docs and terms read; not yet checked live)
applies_to: Phase 6
---

# BounceBan

| | |
|---|---|
| **Role** | Catch-all resolver that answers within the call |
| **Port** | `CatchAllResolver` |
| **Adapter** | `outbound/providers/adapters/bounceban.py::BounceBanResolver` |
| **Registry** | `bounceban` (as `CATCH_ALL_RESOLVER`, or a backup when its key is set) |
| **Settings** | `BOUNCEBAN_API_KEY` |
| **Price** | `bounceban:resolve` 5,000 micro-USD. **Unconfirmed:** the pricing page shows no dollar figure without a login; $40 and $50 for 10,000 credits were both seen elsewhere. Set the real one in `PROVIDER_PRICES` |
| **Cache** | The answer is stored as a `resolve` hit, 90 days |
| **Balance** | `GET https://api.bounceban.com/v1/account`, `available_credits` (-1 means unlimited and is shown as unknown) |
| **Status** | Built from the vendor's docs on 2026-11-20. **Not checked live** |

## Endpoints used

| Operation | Method and path | Auth |
|---|---|---|
| `submit(email)` | `GET https://api-waterfall.bounceban.com/v1/verify/single?email=...&timeout=60` | `Authorization: KEY` (no `Bearer`) |
| `poll(ticket)` | `GET https://api-waterfall.bounceban.com/v1/verify/single/status?id=...` (free), only for a check that outlasted the call | the same |

The waterfall host holds the connection until the address is settled, so the answer normally comes with `submit` and the resolver counts as real time. When the 60 seconds run out the vendor answers HTTP 408 with the check's `id`; the ticket then waits and `poll` reads the answer later, like an asynchronous resolver's.

## Mapping

| BounceBan `result` (with `status: "success"`) | Ours |
|---|---|
| `deliverable` | `valid` (the address becomes `catch_all_resolved`) |
| `undeliverable` | `invalid` |
| `risky` ("may bounce"), `unknown`, anything else | `unresolved` (the address becomes `catch_all_unverified`) |
| `status` of `verifying` or `queue` | no result yet |

- `billed` follows `credits_consumed` (true if absent).
- **HTTP 403 is "out of credits" or "this key's quota is used up",** not a refused key, so the adapter raises `BudgetExceeded`. HTTP 401 is a refused key (or an IP that is not on the key's allow-list).
- A repeat of the same address on this host within 30 minutes is free; later repeats cost a credit, so the meter's cache matters.
- `score` (0 to 100) comes with `risky`; it is not used: only `deliverable` is proof enough to write to.

## Terms that matter (read 2026-11-20; confirm before relying on them)

- **Written approval is needed for our use.** The Terms (updated 2026-11-19) say: "You may not resell the Services, or make them available to third parties as part of your own product, without our prior written approval." Do not turn this vendor on for customers until that approval is in hand.
- **No message is sent to the address:** stated only in the pricing page's FAQ, not in the API docs or the Terms. Ask for it in writing with the approval.
- **Whether a single `unknown` is charged** is not stated (bulk `unknown` results are refunded). The adapter trusts `credits_consumed`.
- **Hosting and data protection:** servers in the United States; the Terms refer to a DPA that is not published, and the privacy notice dates from 2022. Ask for the signed DPA and the sub-processor list.

## Tests and fixtures

`tests/providers/test_bounceban.py` with the resolver contract; fixtures in `tests/providers/fixtures/bounceban/` (deliverable, undeliverable, risky, unknown, verifying, timeout, no_credits, account), all built from the field lists in the vendor's docs, which give no full example answers.

## Data sent to the vendor

Email addresses at catch-all domains.
