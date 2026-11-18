---
type: reference
status: accepted
date: 2026-11-18
deciders: "@rahul-trip"
introduced_in: phase-6/vendor-credit-handling
---

# 0035. Address formats are tried only when a verifier proves them, and real-time resolvers settle catch-alls first

## Context

PLAN rule 9 said "never email guessed permutations": a finder, a published address or a learned company format were the only sources. On 2026-11-18 no finder worked (Hunter's free searches and ZeroBounce's credits were used up), and 58% of the addresses that were found sat on catch-all domains, where a verifier cannot tell a real mailbox from an invented one and the only resolver (Scrubby) takes about 72 hours.

The reason for the rule is that an invented address can bounce, which harms the sender's reputation and may reach a stranger. That harm comes from *sending* to an unproven address, not from *checking* a candidate.

## Decision

- **Rule 9 becomes "never email an unverified guess".** With no known company format, `Waterfall._guess` builds the commonest four (`first.last`, `first`, `flast`, `firstlast`; `patterns.GUESS_PATTERNS`) and asks the verifier about each in turn. The first one the verifier calls valid is used, with provenance `pattern_inferred`, and is learned as the company's format (colleagues then cost one check). A wrong guess is never saved.
- **Where it is not tried.** On a domain already known to accept everything (an address held there is a catch-all), because a verifier proves nothing there; in a country whose rule does not allow an address built from a company format (the same check that holds a guessed Canadian address); when the workspace has switched it off (`guess_verified_addresses`, on by default). A catch-all or unknown answer to a guess stops the guessing and is not sent to a resolver, so a catch-all domain costs one check, not four.
- **Real-time resolvers first.** `ResolverChain` asks the resolvers whose answer comes with the call (OrbiSearch, Enrichley) before the asynchronous one (Scrubby). One that cannot decide hands over to the next; if none decides, the lead is queued with Scrubby as before. `realtime_answer` also lets the poller, and `Waterfall._reuse` for a held unproven catch-all, take a real-time answer without waiting.
- **OrbiSearch is also a resolver** (`OrbiSearchResolver`): the same check as its verifier, asked of an address another verifier called catch-all. Its accuracy on catch-all domains is the vendor's claim; the bake-off measures it before it becomes the main verifier.

## Consequences

- A guess costs up to four verifier checks per person (about a cent at MyEmailVerifier's price, a fifth of a cent at OrbiSearch's), cached for 90 days. It removes the finder call (about 2.5 cents at Hunter, 16 at ZeroBounce) whenever a format is proven.
- A mailbox that exists but is not the person's (a role account, a different person with the same initial) can still verify as valid; the verifier proves existence, not ownership. Only the first two formats, which carry the person's name, are likely to be right, and the others are lower-risk to the extent the company uses them for everyone. If this shows up as bounces, the guess list is one constant to shorten, and the setting turns it off per workspace.
- The email stage keeps its rule that only someone who decides is written to; guessing does not widen who is looked up.
