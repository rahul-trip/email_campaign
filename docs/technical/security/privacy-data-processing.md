---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Privacy and data processing

This is the technical record of the personal data Outbound processes: what it holds, where, why, who else receives it, how long it is kept, and how each data-subject right is served. It is evidence for the operator's own records: the record of processing activities (GDPR Art. 30), the legitimate-interests assessment, and any DPIA. The **policy** (lawful basis, country rules) is in [PLAN.md §11](../../PLAN.md#11-compliance-and-deliverability). It is not legal advice.

## Whose data

| Data subject | How they enter | Typical data |
|---|---|---|
| **Prospects**: people at target companies | Research (company pages, a public LinkedIn-title search), vendors (finders), the operator (intake, Add a person), the webhook | Name, job title, work email, LinkedIn URL, consent records, emails written to them |
| **The operator** (the sender) | Settings | Name, title and signature, the company's legal details and postal address (the sender profile) |
| **Website visitors** (the operator using the app) | HTTP requests | IP address in logs ([R-14](../tech-debt-and-risks.md#r-14--p2--privacy-personal-data-in-logs)) |

## What is held, and where

Column-level detail is in [schema](../data/schema.md). These are the places that can hold personal data:

| Table and columns | Contents | Erased by forget |
|---|---|---|
| `contacts`: `full_name`, `first_name`, `last_name`, `title`, `seniority`, `linkedin_url` | The person | Blanked |
| `contact_emails`: `email`, `found_by`, `verified_by`, `resolution_ref` | Work addresses and how they were found | Blanked; the address is suppressed (as a hash) |
| `consents`: `evidence` | Proof of consent, free text | `[erased]` |
| `notes`: `body` | Operator and import notes, which may name the person | `[erased]` for notes about the person or mentioning their address |
| `messages`: `subject`, `generated_body`, `final_body`, `snippets` | Emails to the person | `[erased]` / blanked |
| `inbound_messages`: `from_address`, `body_excerpt`, `extracted` | Replies (Phase 4; not written yet) | Blanked |
| `provider_calls`: `response` | Vendors' answers: addresses, names, page text | Blanked for calls about the person, or containing their address or full name |
| `import_rows`: `raw` | The row as submitted | `{"erased": true}` where it contains the address |
| `companies`: `research`, `research_answers`, `fit_reason` | Research may quote people's names and published addresses (`research.site_emails`) | Substring-redacted |
| `events`: `data` | Old and new values of changes | `{"erased": true}` for the person, their addresses and messages |
| `suppressions`: `value_hash` | SHA-256 of an address or domain, unsalted ([R-07](../tech-debt-and-risks.md#r-07--p1--data-no-backups-no-retention-unsalted-suppression-hashes-a6-e3)) | Kept: it is what makes erasure stick |
| `workspaces`: `sender_profile` | The operator's own details | — |
| `mailboxes`: `address` | The operator's mailbox | — |
| **Outside the database** | Drafts and sent mail in the mailbox; vendors' own logs and caches; container logs (IPs, masked addresses); Supabase backups | See [data lifecycle](../data/data-lifecycle.md#outside-the-database) |

**Data minimisation.** What is deliberately *not* collected:

- LinkedIn profiles are never fetched or scraped; only a public search result's title is read.
- Free-mail addresses are refused unless the operator allows them for a row.
- No tracking pixels or link tracking: touch 1 contains no links.
- People who cannot be placed at the company are kept `unconfirmed` and not worked on. People at other companies are dropped.

## Purposes

| Purpose | Data used |
|---|---|
| Decide whether a company fits and may lawfully be contacted | Company data, country, legal entity, consents |
| Find the right person and a deliverable work address | Name, title, LinkedIn URL, addresses |
| Write a relevant first email | Name, title, research, notes |
| Honour opt-outs and erasure | Suppression hashes, events |
| Account for spend and audit decisions | Ledger, events |
| Operate and secure the service | Logs |

## Recipients (sub-processors)

Every row below receives personal data from Outbound. The operator must hold appropriate terms (a DPA, and transfer safeguards where the vendor is outside the UK or EEA) with each one, and should list them in their privacy notice. Locations and retention depend on each vendor's terms and the account's settings; they are not recorded here.

| Recipient | Receives | Integration |
|---|---|---|
| Tavily | Company names and domains, page URLs, job titles in search queries | [tavily](../integrations/tavily.md) |
| Hunter | First and last names with company domains; addresses | [hunter](../integrations/hunter.md) |
| ZeroBounce | Names with domains; addresses | [zerobounce](../integrations/zerobounce.md) |
| MyEmailVerifier | Addresses | [myemailverifier](../integrations/myemailverifier.md) |
| OrbiSearch | Addresses | [orbisearch](../integrations/orbisearch.md) |
| Enrichley or Scrubby (catch-all resolver) | Addresses | [enrichley](../integrations/enrichley.md), [scrubby](../integrations/scrubby.md) |
| The LLM provider (Anthropic by default) | Page text, people's names and titles, notes, drafts and edits | [llm](../integrations/llm.md) |
| Companies House | Company names | [companies-house](../integrations/companies-house.md) |
| The mailbox provider | Drafts (recipient, subject, body) | [imap-mailbox](../integrations/imap-mailbox.md) |
| Supabase | Everything in the database | [platform-supabase](../integrations/platform-supabase.md) |
| Doppler | Secrets only, no personal data | [platform-doppler](../integrations/platform-doppler.md) |
| Google Cloud (the VM host) | Container logs (IPs, masked addresses), the encrypted Doppler fallback | — |

## Retention

There is **no automatic retention** today ([R-07](../tech-debt-and-risks.md#r-07--p1--data-no-backups-no-retention-unsalted-suppression-hashes-a6-e3), Phase 3b A6). Records stay until the operator forgets, deletes or suppresses them. The proposed first step blanks `provider_calls.response` after 90 days (Phase 3b A6; the period is a decision for the operator). Container logs rotate at 10 MB × 5 files per container.

## Data-subject rights

| Right | How it is served | Code |
|---|---|---|
| **Object or opt out** (PECR, GDPR Art. 21; the footer's "reply unsubscribe") | The operator reads replies (Phase 4 automates this) and uses **Suppress** on the person or domain: unsent messages are cancelled and drafts deleted, and the address can never be used again | `PrivacyService.suppress_contact`, `suppress_value` |
| **Erasure** (Art. 17) | **Forget** (lead page, `POST /api/privacy/forget`, `outbound forget`): suppress the address; cancel unsent messages; scrub every personal field in every table; delete drafts; one `forgotten` event with no personal data. A test scans every text column afterwards | `PrivacyService.forget`, `outbound/services/forget.py::forget_email` |
| **Access** (Art. 15) | **No built-in export** ([R-23](../tech-debt-and-risks.md#r-23--p2--privacy-no-way-to-answer-a-subject-access-request)). Answered by hand with the queries in the [erasure-request runbook](../operations/runbooks/erasure-request.md) | — |
| **Rectification** (Art. 16) | **Edit** a person or lead; operator values are protected from being overwritten (`manual_fields`) | `LeadService.update_person`, `update` |
| **Restriction** (Art. 18) | Suppress (stops all processing towards them) or hold the lead | — |

Erasure has limits, described in [data lifecycle](../data/data-lifecycle.md#outside-the-database):

- the hashed suppression entry stays, by design;
- sent mail stays in the operator's mailbox;
- vendors' copies are governed by their terms;
- backups age out on Supabase's schedule.

## Security of processing

See the [threat model](threat-model.md). In short:

- TLS on every external hop (the database's TLS depends on `sslmode` in the URL);
- secrets only in Doppler;
- a single authenticated operator;
- personal data kept out of logs by design and by a redaction processor (except IPs);
- every change to a lead is an event.

## How to refresh this page

```bash
grep -n "mapped_column" outbound/db/models.py | grep -i "name\|email\|title\|linkedin\|body\|subject\|evidence\|raw\|research\|response\|address\|excerpt\|data"
sed -n '/def scrub_contact/,/def delete_company/p' outbound/db/repositories/erasure.py
grep -n "BASE_URL =" outbound/providers/adapters/*.py
```
