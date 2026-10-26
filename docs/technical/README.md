---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Technical documentation

This is the engineering documentation for the Outbound engine. It covers how the system is built, why it is built that way, how it is run, and where it is weak. Each page is written from the code and checked against it. Where a page and the code disagree, the code is right and the page has a bug.

Product decisions and compliance policy stay in [PLAN.md](../PLAN.md). How the operator uses the app stays in [USER_MANUAL.md](../USER_MANUAL.md). What to build next stays in [phases/](../phases/README.md).

## Start here

| You are… | Read, in order |
|---|---|
| **New to the code** | [Developer onboarding](guides/developer-onboarding.md) → [Architecture](architecture/architecture.md) → [HLD](hld/hld.md) → the [LLD](#low-level-design) of the module you will change → [Definition of done](quality/definition-of-done.md) |
| **Running it in production** | [Deployment](operations/deployment.md) → [Production readiness](operations/production-readiness.md) → [Runbooks](operations/runbooks/README.md) → [Observability](operations/observability.md) |
| **Reviewing security or privacy** | [Threat model](security/threat-model.md) → [Privacy and data processing](security/privacy-data-processing.md) → [Secrets](security/secrets-management.md) → [ASVS L1 checklist](security/asvs-l1-checklist.md) |
| **Integrating with it** | [API conventions](api/api-conventions.md) → [API reference](api/api-reference.md) → [Webhook integration](api/webhook-integration.md) |
| **Asking "why is it like this?"** | [Architecture decision records](adr/README.md) |
| **Asking "what is wrong with it?"** | [Tech debt and risks](tech-debt-and-risks.md) |
| **An AI coding agent** | [CLAUDE.md](../../CLAUDE.md) first (binding rules), then the LLD of the module you touch |

## Map

The pages follow [Diátaxis](https://diataxis.fr/). Each page is one of four types, declared in its front-matter:

- **Explanation (E):** why and how it fits together.
- **Reference (R):** facts to look up.
- **How-to (H):** steps for a task.
- **Tutorial (T):** a guided first experience.

### Architecture and high-level design

| Page | Type | What it answers |
|---|---|---|
| [architecture/architecture.md](architecture/architecture.md) | E | The arc42 description: goals, constraints, C4 views, runtime, deployment, cross-cutting concepts |
| [architecture/quality-attributes.md](architecture/quality-attributes.md) | R | The non-functional requirements as testable scenarios, and what proves each |
| [hld/hld.md](hld/hld.md) | E | How the parts work together: queue, transactions, tenancy, integration, limits |
| [hld/pipeline-flow.md](hld/pipeline-flow.md) | E | One lead through every stage, as sequence diagrams |
| [hld/state-machines.md](hld/state-machines.md) | R | Every status, every allowed transition, and what writes the event |
| [hld/safety-model.md](hld/safety-model.md) | E | Every check that stands between a lead and an email, and where each is made again |

### Low-level design

One page per module, all from the same [template](_templates/lld.md).

| Page | Code |
|---|---|
| [lld/domain.md](lld/domain.md) | `outbound/domain/` |
| [lld/persistence.md](lld/persistence.md) | `outbound/db/` |
| [lld/providers.md](lld/providers.md) | `outbound/providers/` (ports, HTTP, registry) |
| [lld/metering.md](lld/metering.md) | `outbound/metering/` |
| [lld/stage-research.md](lld/stage-research.md) | `outbound/stages/research/`, `outbound/prompts/research.py` |
| [lld/stage-gate-and-contacts.md](lld/stage-gate-and-contacts.md) | `outbound/stages/gate.py`, `policy.py`, `contacts.py` |
| [lld/stage-email.md](lld/stage-email.md) | `outbound/stages/email/` |
| [lld/stage-copy.md](lld/stage-copy.md) | `outbound/stages/copy/`, `outbound/prompts/copy.py` |
| [lld/stage-deliver-and-sync.md](lld/stage-deliver-and-sync.md) | `outbound/stages/deliver.py`, `sync.py` |
| [lld/runner-and-worker.md](lld/runner-and-worker.md) | `outbound/runner/`, `outbound/worker.py` |
| [lld/services.md](lld/services.md) | `outbound/services/` |
| [lld/api.md](lld/api.md) | `outbound/api/` |
| [lld/cli.md](lld/cli.md) | `outbound/cli/` |
| [lld/web-frontend.md](lld/web-frontend.md) | `web2/` |
| [lld/configuration-and-bootstrap.md](lld/configuration-and-bootstrap.md) | `outbound/config.py`, `bootstrap.py`, `pipeline.py` |
| [lld/logging.md](lld/logging.md) | `outbound/logging.py`, `outbound/api/request_log.py` |

### Data, API and integrations

| Page | Type | What it answers |
|---|---|---|
| [data/schema.md](data/schema.md) | R | Every table, column, constraint and relationship |
| [data/data-lifecycle.md](data/data-lifecycle.md) | E | How a record is created, changed, kept and erased |
| [data/migrations.md](data/migrations.md) | R | How the schema changes, and the log of every migration |
| [api/api-reference.md](api/api-reference.md) | R | Every endpoint |
| [api/api-conventions.md](api/api-conventions.md) | R | Auth, CSRF, errors, concurrency, versioning |
| [api/webhook-integration.md](api/webhook-integration.md) | H | Sending targets in from another system |
| [integrations/README.md](integrations/README.md) | R | Every vendor and platform, with cost, cache and retry behaviour |

### Security, operations and quality

| Page | Type | What it answers |
|---|---|---|
| [security/threat-model.md](security/threat-model.md) | E | Trust boundaries, threats, mitigations, residual risk |
| [security/privacy-data-processing.md](security/privacy-data-processing.md) | R | What personal data is held, where it goes, how long, how it is erased |
| [security/secrets-management.md](security/secrets-management.md) | R/H | Every secret, where it lives, how to rotate it |
| [security/supply-chain.md](security/supply-chain.md) | R | Dependencies, scanning, pinning, the build |
| [security/asvs-l1-checklist.md](security/asvs-l1-checklist.md) | R | OWASP ASVS level 1, item by item |
| [operations/deployment.md](operations/deployment.md) | H | Setting up the VM and deploying |
| [operations/environments.md](operations/environments.md) | R | Each environment and how it differs |
| [operations/configuration-reference.md](operations/configuration-reference.md) | R | Every setting |
| [operations/release-and-rollback.md](operations/release-and-rollback.md) | R/H | What a release is, and how to go back |
| [operations/observability.md](operations/observability.md) | R | Logs, every log event, the event table, the cost ledger |
| [operations/slos.md](operations/slos.md) | R | Service levels and how they are measured |
| [operations/capacity-and-limits.md](operations/capacity-and-limits.md) | R | Connection, rate, spend and memory limits |
| [operations/backup-and-dr.md](operations/backup-and-dr.md) | R/H | Backups, recovery targets, the restore drill |
| [operations/data-fixes.md](operations/data-fixes.md) | H | How to write and run a one-off data correction |
| [operations/incident-response.md](operations/incident-response.md) | H | What to do when something breaks |
| [operations/production-readiness.md](operations/production-readiness.md) | R | Is it ready for live use? Item by item, with evidence |
| [operations/runbooks/](operations/runbooks/README.md) | H | One page per symptom |
| [quality/testing-strategy.md](quality/testing-strategy.md) | E/R | How the code is tested, and where each rule is proven |
| [quality/ci-cd.md](quality/ci-cd.md) | R | Every CI and deploy job |
| [quality/definition-of-done.md](quality/definition-of-done.md) | R | What a change needs before it merges |
| [guides/](guides/developer-onboarding.md) | T/H | Onboarding, and how to add an adapter, status, migration, endpoint, screen or data fix |
| [adr/](adr/README.md) | R | Architecture decision records |
| [tech-debt-and-risks.md](tech-debt-and-risks.md) | R | Known defects, gaps and risks, with severity and owner |
| [glossary.md](glossary.md) | R | Terms |

## Where each fact lives

Facts that change with the code live on **one page only**. Every other page links to that page and does not copy the fact.

| Fact | Its one home |
|---|---|
| Product rules, scope, decisions, compliance policy | [PLAN.md](../PLAN.md) |
| What the operator clicks and types | [USER_MANUAL.md](../USER_MANUAL.md) |
| Statuses and transitions | [hld/state-machines.md](hld/state-machines.md), from `outbound/domain/state_machines.py` |
| Tables and columns | [data/schema.md](data/schema.md) |
| Settings | [operations/configuration-reference.md](operations/configuration-reference.md), from `outbound/config.py::Settings` |
| Endpoints | [api/api-reference.md](api/api-reference.md); the machine-readable contract is `web2/openapi.json` |
| Vendor prices | [integrations/README.md](integrations/README.md), from `outbound/providers/pricing.py` |
| Log event names | [operations/observability.md](operations/observability.md) |
| Design tokens | [design.md](../design.md) |
| Known defects and gaps | [tech-debt-and-risks.md](tech-debt-and-risks.md) |

## Conventions for these pages

**Front-matter.** Every page starts with:

```yaml
---
type: explanation | reference | how-to | tutorial
status: draft | reviewed | deprecated
owner: "@rahul-trip"
last_verified: YYYY-MM-DD (short commit SHA the page was checked against)
applies_to: Phase N
---
```

**Citing code.** Name the file and the symbol, for example `outbound/metering/metered.py::Meter.call`. Never cite a line number: line numbers go stale with every edit.

**Diagrams.** Use Mermaid only, because it renders on GitHub and diffs in a PR. Put one idea in each diagram. Use no images.

**Binding words.** MUST, MUST NOT, SHOULD and MAY ([RFC 2119](https://www.rfc-editor.org/rfc/rfc2119)) appear only in rules: [CLAUDE.md](../../CLAUDE.md), the API conventions and the templates. Explanations use plain English.

**Gaps.** When a page describes something that is missing or wrong, it says so in one line and links the [register](tech-debt-and-risks.md) entry (for example `R-03`). Pages never describe intended behaviour as if it were real.

**Later phases.** Each page ends with a short **Planned** section. It links to the phase document and does not describe the future design.

**Refreshing.** Every reference page ends with **How to refresh this page**: the read-only commands that re-derive its facts from the code. Run them when you verify the page.

**Style.** Follow the house style of the manual and the plan: plain English, short sentences, tables for reference material. Write for a reader who knows Python and web apps but not this code.

## Keeping the pages true

Each kind of change has pages it must update in the same pull request. The [pull request template](../../.github/pull_request_template.md) repeats this list as a checklist, and [CLAUDE.md](../../CLAUDE.md) makes it binding.

| If the change… | It also updates |
|---|---|
| Changes behaviour | The module's LLD; [PLAN.md](../PLAN.md) if it changes a product rule |
| Changes data | A migration, [data/schema.md](data/schema.md), [data/migrations.md](data/migrations.md) |
| Adds or changes a setting | [operations/configuration-reference.md](operations/configuration-reference.md) |
| Adds or changes an endpoint | `npm run gen:api`, [api/api-reference.md](api/api-reference.md) |
| Adds or renames a log event | [operations/observability.md](operations/observability.md) |
| Changes the deploy | [operations/deployment.md](operations/deployment.md), [operations/release-and-rollback.md](operations/release-and-rollback.md), the affected runbooks |
| Adds a way to fail | A runbook |
| Makes an architecturally significant decision | An [ADR](adr/README.md) |
| Adds or changes a vendor | Its integration page and [integrations/README.md](integrations/README.md) |
| Changes a screen | The tour and the manual (existing rule) |
| Finds or fixes a defect | [tech-debt-and-risks.md](tech-debt-and-risks.md) |

**Review cadence.** Every phase gate includes a documentation pass: re-run each reference page's refresh commands, update `last_verified`, and walk the [production readiness](operations/production-readiness.md) checklist again. ADRs are never edited after acceptance; a new ADR supersedes an old one.

**Templates** for new pages are in [_templates/](_templates/).
