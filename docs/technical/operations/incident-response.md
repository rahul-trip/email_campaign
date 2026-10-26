---
type: how-to
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Incident response

What to do when something goes wrong in production. There is one operator and one maintainer, so this is a short procedure, not a rota. It still matters: some incidents (a wrong email, a privacy breach) have legal clocks.

## Severity

| Severity | Examples | Respond |
|---|---|---|
| **SEV-1** | An email drafted or sent that breaks the safety model (suppressed, blocked country, wrong person, unconsented); personal data exposed; a secret leaked; runaway spend | At once. Stop the worker first |
| **SEV-2** | The app is down; deploys fail and roll back badly; the worker crash-loops; an erasure request near its deadline; vendors failing for every lead | Same working day |
| **SEV-3** | One lead stuck; a vendor intermittently slow; an ambiguous Sent match; a cosmetic bug | Next working day, through the normal backlog |

## The first 15 minutes

1. **Contain.**
   - For SEV-1: stop the worker (`oc stop worker`) so nothing more is drafted or spent. Cancel any queued run in the Runs screen.
   - If a draft is wrong, delete it from the mailbox, and suppress the address or domain.
   - If a secret leaked, follow [secret leaked](runbooks/secret-leaked.md).
2. **Find the runbook.** Match the symptom in the [runbooks](runbooks/README.md).
3. **Write things down.** Note the time (UTC), what you saw, and what you did, in a private incident note. Never paste personal data or secrets into chat, tickets or the note; use ids and domains.
4. **Get the evidence:**
   - logs: `oc logs --since 2h api worker > incident.log`, kept privately and deleted when done;
   - the lead's timeline (events);
   - the run's counts;
   - `provider_calls` for the period.

## Personal-data breaches

If personal data may have been exposed, for example a leaked database URL, an email to the wrong person, or logs shared publicly:

- The operator is the controller and decides whether to notify. Under UK and EU GDPR, a notifiable breach must be reported to the regulator **within 72 hours** of becoming aware of it.
- Record the facts at once: what data, whose (ids and counts), how, since when, and what was done.
- Rotate any exposed secret; suppress any affected person who asks; forget on request.

## After the incident

For every SEV-1 and SEV-2, write a short **blameless postmortem** ([template](../_templates/postmortem.md)) within a week:

- impact;
- timeline;
- root cause;
- what went well and badly;
- actions.

Each action becomes a [register](../tech-debt-and-risks.md) entry or a phase item. Fix the system, not the person.

## Useful commands

```bash
cd /opt/outbound/current && export RELEASE=$(basename "$(readlink /opt/outbound/current)")
alias oc='docker compose -p outbound -f deploy/compose.yml'
oc ps -a; oc stop worker; oc start worker
oc logs --since 1h worker | grep -E '"level": "(error|warning)"'
oc run --rm --no-deps api outbound status
oc run --rm --no-deps api outbound suppress example.com
```
