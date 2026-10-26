---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Domain

**Code:** `outbound/domain/` · **Layer:** domain (the bottom) · **Tests:** `tests/domain/` (no database, no network)

## Purpose

The domain holds the business rules as plain functions over plain data: lifecycles, the country policy, the safe-to-send rule, the fit gate, contact ranking, name matching, the copy linter, the footer, and the value conventions. It exists as its own layer so every rule can be read in one place and tested in microseconds, without a database or a vendor.

## Responsibilities

- Define every closed value set (`StrEnum`) and every entity the other layers pass around (frozen dataclasses).
- Define the five lifecycles as transition tables ([state machines](../hld/state-machines.md)).
- Decide country policy, safe-to-send, fit and skips ([safety model](../hld/safety-model.md)).
- Rank contacts, match names to employers, lint copy, render footers, measure edits.
- Hold the money, id, time-free hashing and domain conventions.

**Not its job:**

- reading or writing data (`db/`);
- calling vendors (`providers/`);
- deciding *when* a rule runs (`stages/`, `runner/`, `services/`).

## Rules this layer obeys

- **No I/O, no upward imports.** The import-linter contract "The domain does no I/O" forbids importing `outbound.db`, `providers`, `metering`, `stages`, `runner`, `services`, `api`, `cli`, `sqlalchemy`, `httpx` and `requests` (`pyproject.toml`).
- **mypy strict** applies to `outbound.domain.*`.
- **Deterministic.** `domains.py` uses the public-suffix snapshot bundled with `tldextract` and never fetches it, so results do not change between runs.

## Public interface

| Module | Main symbols | What it does |
|---|---|---|
| `enums.py` | 26 `StrEnum`s, e.g. `CompanyStatus`, `HoldReason`, `ContactStatus`, `EmailStatus`, `Provenance`, `PolicyRule`, `PolicyStage`, `MessageState`, `RunStatus`, `CallOutcome`; `WORKABLE_CONTACT_STATUSES` | Every closed value set. Each is mirrored by a `CHECK` constraint ([schema](../data/schema.md)) |
| `entities.py` | `Company`, `Contact`, `ContactEmail`, `Message`, `Note`, `Consent`, `Workspace`, `Campaign`, `CountryPolicy`, `Event`, `ProviderCall`, `Suppression` | Frozen dataclasses with the same field names as the columns. Repositories return these, never ORM rows |
| `state_machines.py` | `StateMachine`, `COMPANY`, `MESSAGE`, `EMAIL`, `CONTACT`, `RUN`, `IllegalTransition`, `STAGE_INPUT_STATUS`, `resume_status_for`, `retry_status_for`, `POLICY_STAGE_AT`, `RESUME_AFTER_SKIP` | Lifecycles; see [state machines](../hld/state-machines.md) |
| `policies.py` | `decide_country_policy`, `PolicyDecision`, `PolicyOutcome`, `policy_skipped_at`, `skipped_decision`, `is_safe_email_status`, `is_sendable`, `check_send`, `SendVerdict`, `passes_fit_gate`, `OPERATOR_CHOSEN` | The three rules: may we contact this lead; may this message go now; does it fit |
| `ranking.py` | `rank_contacts`, `RankedContact`, `seniority_of`, `wanted_index`, `normalise_title` | Orders people for the email step |
| `names.py` | `employer_matches`, `mentions_company`, `same_person`, `read_profile_title`, `split_name`, `split_person`, `clean_person_name`, `company_tokens`, `domain_label`, `display_name` | Name and employer matching |
| `copy_lint.py` | `lint`, `LintRules`, `LintReport`, `LintIssue`, `reading_grade`, `count_words`, `BANNED_PHRASES` | Deterministic copy checks |
| `footer.py` | `render_footer`, `DEFAULT_FOOTER`, `DATA_SOURCE`, `MissingProfileField` | The legal footer from a template and the sender profile |
| `policy_seeds.py` | `DEFAULT_COUNTRY_POLICIES` | The seeded country rules (version 1) |
| `editing.py` | `edit_distance` | How much the operator changed a draft, 0 to 1 |
| `domains.py` | `registrable_domain`, `is_free_mail`, `is_platform`, `FREE_MAIL_DOMAINS`, `PLATFORM_DOMAINS` | Root domains, offline |
| `countries.py` | `country_code` | A country name or code → ISO alpha-2 |
| `money.py` | `usd_to_micro`, `micro_to_usd`, `format_usd`, `MICRO` | Integer micro-USD ([ADR 0010](../adr/0010-money-ids-and-time.md)) |
| `ids.py` | `new_id` | UUIDv7 strings |
| `hashing.py` | `normalise`, `hash_value` | SHA-256 of a trimmed, lower-cased value (suppressions) |
| `actors.py` | `OPERATOR`, `SYSTEM`, `provider`, `is_operator` | Who did something, for events |
| `errors.py` | `InvalidInput`, `ConfigurationError` | Domain-level errors |

## How the rules work

### Country policy

`decide_country_policy(country_code, legal_entity_type, policy, email_provenance, has_active_consent)` returns a `PolicyDecision` (`outcome`, `reasons`, `hold_reason`, `rule`, `footer_template`, `policy_version`, `skipped`). The order of checks and their outcomes is in the [safety model](../hld/safety-model.md#2-country-policy). Two properties matter to callers:

- **Consent overrides** every hold and block, except an unknown country.
- **`email_provenance` is `None` before an address exists.** The provenance check runs only once one is chosen.

The function knows nothing about skips or recipients. `outbound/stages/policy.py::policy_decision_for` adds those ([gate and contacts](stage-gate-and-contacts.md)).

`policy_skipped_at(stage, skip_from)` is true when `stage` is at or after `skip_from` in `PolicyStage` order (`gate < contacts < email < copy < deliver`). With `stage=None` (a hold being released) it is true whenever any skip is set.

### Safe to send

- `is_sendable(status, verification_skipped, safe_to_send_only)` is true for `valid` and `catch_all_resolved`. It is true for `catch_all_unverified` only when `safe_to_send_only` is off, and for **any** status when `verification_skipped` is set.
- `check_send(...)` combines all five conditions:
  - a sendable address;
  - the address is not suppressed;
  - the domain is not suppressed;
  - the policy is ALLOW;
  - the contact is workable.

  It reports **every** failing reason, not just the first.

### Fit gate

`passes_fit_gate(source, fit_score, min_fit_score)` lets leads from `manual`, `import` and `referral` through (`OPERATOR_CHOSEN`). Discovered leads need a score of at least the campaign minimum.

### Ranking

`rank_contacts(contacts, wanted_titles, chosen_ids)` sorts best first and gives consecutive ranks from 1.

1. **People the operator chose come first, in their existing rank order.** That means people added by the operator (`source = operator`), plus `chosen_ids`: people the operator gave an address or recorded consent for ([ADR 0022](../adr/0022-consent-belongs-to-the-recipient.md)).
2. Everyone else is ordered by:
   1. the position of their title in the campaign's wanted titles;
   2. seniority, in the order `vp`, `c_level`, `director`, `manager`, `other` (via `seniority_of`, which expands common abbreviations). Note that a VP ranks above a C-level title here ([R-21](../tech-debt-and-risks.md#r-21--p3--ranking-a-vp-outranks-a-c-level-person-on-a-seniority-tie));
   3. their previous rank.

### Name matching

`employer_matches(employer, company, domain)` is true when the employer contains **all** of the company's identifying words (`company_tokens` drops accents and suffixes such as Ltd, Inc, Group), or the website's name (`domain_label`, three or more characters). One shared word is never enough ([ADR 0023](../adr/0023-discovery-stores-websites-unconfirmed-people.md)). `mentions_company` applies the same test to free text. `same_person` ignores case and accents, and lets a first name match a full name.

### Copy linter

`lint(body, subject, step, footer)` measures the body **without** the footer and returns a `LintReport` of `LintIssue`s:

| Code | Rule (defaults in `LintRules`) |
|---|---|
| `length` | 50–85 words for step 0; 25–50 for follow-ups |
| `subject` | 2–5 words, all lower case |
| `reading_level` | Flesch–Kincaid grade ≤ 6.5 (computed in `reading_grade`, no external word list) |
| `call_to_action` | Exactly one `?` |
| `links` | No link in step 0 |
| `address_in_body` | No email address in the body |
| `banned_phrase` | None of `BANNED_PHRASES` ("i hope this email finds you well", "leverage", "touch base", …) |
| `footer` | The required footer is present |

A report with any issue is *flagged*. The copy stage still hands the draft to the operator, with the reasons attached ([copy](stage-copy.md)).

### Footer

`render_footer(template, sender, provenance)` fills `{placeholders}` from the sender profile, plus `{data_source}` from the address provenance (`DATA_SOURCE`). A blank field the template needs raises `MissingProfileField` with the list of missing fields, because a footer with a hole in it is not legal. `DEFAULT_FOOTER` is used when footers are on and the country has none.

### Seeded country rules

`DEFAULT_COUNTRY_POLICIES` is version 1, seeded with no reviewer. A lawyer confirms the values before Phase 5 ([PLAN.md §11](../../PLAN.md#11-compliance-and-deliverability)).

| Country | Rule | Extra condition | Footer |
|---|---|---|---|
| US | allow with footer | — | identity, postal address, opt-out |
| GB | allow with footer | corporate subscribers only (PECR) | identity, registration, data source, opt-out, right to object |
| DE, AT | block | — | — |
| FR, NL, IE, SE | allow with footer | — | identity, address, data source, legitimate interest, opt-out |
| CA | allow with footer | address provenance `operator_given` or `publicly_published` (CASL) | identity, address, contact, opt-out |
| IN | consent required | — | — |
| ZZ (unknown) | consent required | held as `country_unknown` by the decision logic | — |

The operator can add, edit and remove rules; every change writes `policy_changed` or `policy_deleted` and bumps the policy `version`.

## Invariants

- Every state has a row in its transition table, or the module fails to import.
- `usd_to_micro` refuses floats.
- `new_id` returns a UUIDv7 string, so ids sort by creation time.
- `hash_value` is stable for the same address in any case or with surrounding spaces.

## Errors

| Error | Raised by | Mapped to |
|---|---|---|
| `IllegalTransition` | `StateMachine.check` | API `409 action_not_allowed`; runner: the lead fails at that stage |
| `MissingProfileField` | `render_footer` | Copy stage `StageFailure` naming the fields |
| `InvalidInput` | Callers validating input | API `422 invalid_request` |
| `ConfigurationError` | Callers when setup is incomplete | Startup error |

## Security and privacy

- **Suppression hashes are unsalted SHA-256** ([R-07](../tech-debt-and-risks.md#r-07--p1--data-no-backups-no-retention-unsalted-suppression-hashes-a6-e3)).
- **No personal data is held here.** Names pass through matching functions and are never stored or logged by this layer.

## Tests

| File | Proves |
|---|---|
| `tests/domain/test_state_machines.py` | Every table, finals, illegal moves, helper maps |
| `tests/domain/test_policies.py` | Policy order, consent overrides, skips per stage, safe-to-send, fit |
| `tests/domain/test_ranking.py` | Wanted titles, seniority, operator-chosen first (including a chosen CEO over a wanted CTO) |
| `tests/domain/test_copy_lint.py` | Each lint rule and the reading grade |
| `tests/domain/test_basics.py` | Names, profile titles, employer matching, domains, money, ids, footers |

## Known limitations

- Suppression hashes can be checked against guessed addresses ([R-07](../tech-debt-and-risks.md#r-07--p1--data-no-backups-no-retention-unsalted-suppression-hashes-a6-e3)).
- The seeded country rules are working defaults, not legal advice, and have no reviewer yet.
- On a seniority tie a VP outranks a C-level person ([R-21](../tech-debt-and-risks.md#r-21--p3--ranking-a-vp-outranks-a-c-level-person-on-a-seniority-tie)).

## Extending it

- **A new status or transition:** [add a status or transition](../guides/add-a-status-or-transition.md). The enum, the table, a migration for the `CHECK`, and the docs change together.
- **A new rule:** write it as a pure function here, test it in `tests/domain/`, and call it from the stage or service that owns the timing.

## Planned

- Phase 4 uses the reply categories (`InboundCategory`) and the bounce transitions: [phase-4-close-the-loop.md](../../phases/phase-4-close-the-loop.md).
- Phase 5 uses the send window, cadence and breaker settings: [phase-5-automated-sending.md](../../phases/phase-5-automated-sending.md).

## How to refresh this page

```bash
grep -n "^def \|^class \|^[A-Z_]* = " outbound/domain/*.py
grep -c "class .*(StrEnum)" outbound/domain/enums.py
sed -n '/DEFAULT_COUNTRY_POLICIES/,/^)/p' outbound/domain/policy_seeds.py
uv run pytest tests/domain -q
```
