---
type: reference
status: accepted
date: 2026-11-14
deciders: "@rahul-trip"
introduced_in: phase-6/discovery-platform-domains
---

# 0032. Discovery decides what a company is, and which site is its own, by closed choice

## Context

A live run of the multi-source discovery ([ADR 0031](0031-multi-source-discovery-screened-before-intake.md)) found two faults that string rules cannot fix.

- **Vendors passed.** The screening prompt tells the model to score 40 to 60 when the text says too little, and the pass mark was 50. Four software vendors that the model itself called "a software vendor rather than an operator" scored 50 to 55 and became leads, while real buyers with thin text scored the same.
- **Websites were wrong or missing.** A page that only mentioned a company scored 0.65 and was taken as its site (`tavily.com`, `leadiq.com`); the search returned aggregators and not the company's own site; and the strict fix (the domain must be the company's name) left companies known by initials unresolved (`pse.pl`, `ren.pt`).

## Decision

- **A role, then a score.** Screening returns, for each company, a `role` from a closed list (`buyer`, `vendor`, `competitor`, `investor`, `adviser_or_media`, `unclear`). Only a `buyer` fits, at `SCREEN_MIN`; `unclear` needs `UNCLEAR_MIN`. The score only ranks.
- **The website by number.** A site whose domain is the company's name (0.9 or more) is taken by code. Otherwise a model is shown the likeliest results (title and text) and returns the number of the company's own site, or 0. Anything but a number from the list shown, and any `ProviderError`, means no website.
- **A second look, once.** An unresolved company is looked at again by the next run, and dropped if it is still unresolved.
- **The lookup** searches the plain name (ten results), then `<name> homepage`, instead of `<name> official website` (five), which returned only aggregators for well-known companies.

## Consequences

- **Good:** vendors and unknowns stop passing on a middling score; companies known by initials get their site; a wrong site is refused more often than taken.
- **Bad:** one more model call for each company whose domain is not its name; a model's judgement of "vendor" can be wrong, and a buyer wrongly called a vendor is left out (it stays on the run's page, where **Make a lead** adds it).
- **Pattern:** the model answers from a closed list or a number from a list it was shown, and code validates the answer. Free text from a model never becomes a website or a status.

## Alternatives considered

- *Raise `SCREEN_MIN`.* Drops real grid operators, which score 55 on thin text.
- *Loosen the domain rule to accept a name inside a domain.* Gave SONI `soniassociates.net`.
- *A paid company database.* Out of scope until Exa has been tried.
