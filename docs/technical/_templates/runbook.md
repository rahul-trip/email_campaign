---
type: how-to
status: draft
owner: "@rahul-trip"
last_verified: YYYY-MM-DD (<short SHA>)
applies_to: Phase N
---

<!-- Relative links in this template are written for a page in docs/technical/operations/runbooks/. -->
# <Symptom, as the operator or engineer first sees it>

| | |
|---|---|
| **Severity** | SEV-1 / SEV-2 / SEV-3 (see [incident response](../incident-response.md)) |
| **Impact** | Who or what is affected, and whether money, data or an email to a real person is at risk |
| **Signals** | The log events, screen messages or exit codes that point here |
| **Related** | Register entries, other runbooks |

## 1. Confirm

The commands that tell you that this is the problem and not something that looks like it. Read-only commands come first.

```bash
cd /opt/outbound/current
alias oc='docker compose -p outbound -f deploy/compose.yml'
oc ps
```

## 2. Contain

What to do first to stop it getting worse, such as stopping the worker or pausing runs. Say what each step costs.

## 3. Fix

Steps in order. Each step says what it changes and how to undo it.

## 4. Verify

How to know it is fixed: the log event to look for, the screen to check, the query to run.

## 5. Follow up

What to record: an incident note for SEV-1 and SEV-2 (the [postmortem template](../../_templates/postmortem.md)), and any new [register](../../tech-debt-and-risks.md) entry.

<!-- Rules: write for someone tired and in a hurry. One action per step. Real event names and real
commands only. Never put a secret, an email address or a person's name in a command example. -->
