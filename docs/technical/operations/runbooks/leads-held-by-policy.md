---
type: how-to
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Leads are held by a country rule

| | |
|---|---|
| **Severity** | SEV-3 |
| **Impact** | Leads wait in `held` with `country_unknown`, `entity_unknown`, `consent_required` or `needs_operator`. |
| **Signals** | Needs attention screen; the lead page shows the reason and the fix; **Release** is refused with "Nothing has changed since it was held" |
| **Related** | [safety model](../../hld/safety-model.md), [manual §7.1](../../../USER_MANUAL.md#71-held) |

On the VM, set up the usual alias first:

```bash
cd /opt/outbound/current && export RELEASE=$(basename "$(readlink /opt/outbound/current)")
alias oc='docker compose -p outbound -f deploy/compose.yml'
```

## 1. Confirm

Open the lead page: the hold reason, the policy decision and what would change it are shown.

| Reason | Usual fix |
|---|---|
| `country_unknown` | Set the country (Edit), or confirm the suggested one |
| `entity_unknown` (GB) | Confirm incorporation (Companies House key; or record the legal entity) |
| `consent_required` | Record the recipient's consent (Add a person with consent, or Record consent) |
| `needs_operator` (a block, or no rule for the country) | Add or adjust the country rule; or skip the rule for this lead, with a reason |

## 2. Contain

—

## 3. Fix

Change the cause first, then release. The release is refused while the cause is unchanged, so the lead cannot loop. **Skip the country rule** is the explicit override: it is recorded, and approval must acknowledge it. Switching rules off for the whole workspace is possible (Policies and privacy) but affects every lead, and shows a red banner.

## 4. Verify

The lead moves on, and its timeline shows the change and the release.

## 5. Follow up

If many leads share one cause (for example a country with no rule), fix the rule once.
