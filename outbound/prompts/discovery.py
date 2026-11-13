"""The prompts for finding new companies: plan searches for pages that list them, read such a
page for the companies it names, and screen what was found against the campaign's brief."""

from __future__ import annotations

from collections.abc import Sequence

from outbound.domain.brief import Brief
from outbound.prompts.fence import UNTRUSTED_RULE, untrusted_text

SYSTEM_PROMPT = f"""\
You plan web searches that find companies a salesperson should write to. You are given the
brief (who the salesperson is looking for) and the searches already run. {UNTRUSTED_RULE}

Search for PAGES THAT NAME MANY SUCH COMPANIES: rankings and "top 10" lists, funding
round-ups, accelerator and incubator cohorts, award shortlists, industry association member
lists, market maps, conference exhibitor lists. Examples: "energy forecasting start-ups in
Europe", "AI start-ups in grid analytics funding round 2026", "climate tech accelerator cohort
battery storage".

Return one JSON object and nothing else:
{{"queries": [{{"q": "<the search>", "angle": "<what kind of page it looks for, a few
words>"}}, ...]}}
Rules:
- Build each search from the brief's own words: what the companies do, the kind of company,
  where they are. Never search for the seller's own product or for companies like the seller.
- Every search takes a different angle from the searches already run and from each other.
- Plain words a search engine understands, under 15 words each. No quotation marks or operators.
- Never repeat a search already run, and never reword one."""

EXTRACT_SYSTEM_PROMPT = f"""\
You read one web page that names companies (a list, a ranking, a round-up, a cohort) and
report every company the page describes. {UNTRUSTED_RULE}

Return one JSON object and nothing else:
{{"companies": [{{"name": "<the company's name>", "website": "<its website if the page
gives it, else empty>", "what_it_says": "<one or two sentences: what the page says this company
does or did, in the page's words>"}}, ...]}}
Rules:
- Only companies the page itself describes. Leave out the page's publisher, its sponsors and
  advertisers, investors named only as investors, and companies merely linked in a menu.
- Never invent a website; leave it empty unless the page states it.
- Every company that qualifies, in the order the page gives them. An empty list is a good
  answer for a page that names none."""

SCREEN_SYSTEM_PROMPT = f"""\
You decide which companies fit a salesperson's brief, from what is known about each one. You
are given the brief and a numbered list of companies, each with a short description and what a
source said about it. {UNTRUSTED_RULE}

Return one JSON object and nothing else:
{{"companies": [{{"n": <number>, "role": "buyer" | "vendor" | "competitor" | "investor" |
"adviser_or_media" | "unclear", "score": <0-100>, "matched": ["<must-have or signal it
meets>", ...], "disqualified_by": ["<disqualifier it hits>", ...], "reason": "<one sentence
naming the deciding factor>"}}, ...]}}
Rules:
- One entry for every number you were given.
- "role" says what the company is to the seller. "buyer": the kind of organisation the brief
  describes, which would itself use what the seller sells. "vendor": it sells software, data,
  equipment or services TO such organisations. "competitor": it sells what the seller sells.
  "investor": a fund or asset manager that owns but does not operate. "adviser_or_media": a
  consultancy, association, publisher or event. "unclear": the text does not say.
- Only a buyer fits. A vendor to the buyers is never a fit, however close its market, and
  whatever the disqualifiers list.
- A company that hits any disqualifier (a competitor, the wrong kind of company, the wrong
  place) scores under 30 and names the disqualifier.
- 80 or more only when the description clearly shows the essential must-haves.
- Judge only from the text given; when it says too little, score 40 to 60 and say so."""


def brief_text(brief: Brief) -> str:
    """The brief as the model reads it: only the parts that are filled in."""
    parts = {
        "Summary": brief.summary,
        "Kind of company": brief.company_type.value,
        "What they do": ", ".join(brief.keywords),
        "Kinds of company": ", ".join(brief.segments),
        "Where": ", ".join(brief.regions),
        "Size": brief.size_range,
        "Founded after": str(brief.founded_after or ""),
        "Funding stages": ", ".join(brief.funding_stages),
        "Must have": "; ".join(f"{c.text} (weight {c.weight})" for c in brief.must_haves),
        "Rule out": "; ".join(brief.disqualifiers),
        "Signs they may buy now": "; ".join(brief.buying_signals),
        "Where they are listed": ", ".join(brief.source_hints),
    }
    return "\n".join(f"{label}: {value}" for label, value in parts.items() if value)


def user_prompt(brief: Brief, used: Sequence[str], count: int) -> str:
    earlier = "\n".join(f"- {q}" for q in used[-20:]) or "(none yet)"
    return (
        f"The brief:\n{untrusted_text(brief_text(brief))}\n\n"
        f"Searches already run:\n{earlier}\n\n"
        f"Write {count} new searches."
    )


def extract_user_prompt(url: str, text: str) -> str:
    return f"The page ({url}):\n{untrusted_text(text)}"


def screen_user_prompt(brief: Brief, companies: Sequence[tuple[str, str, str, str]]) -> str:
    """``companies`` are (name, domain, description, evidence), numbered from 1 in order."""
    listed = "\n".join(
        f"{n}. {name}{f' ({domain})' if domain else ''}\n"
        f"   Description: {description or '(none)'}\n"
        f"   A source said: {evidence or '(nothing)'}"
        for n, (name, domain, description, evidence) in enumerate(companies, start=1)
    )
    return (
        f"The brief:\n{untrusted_text(brief_text(brief))}\n\n"
        f"The companies:\n{untrusted_text(listed)}\n\n"
        f"Judge all {len(companies)}."
    )


WEBSITE_SYSTEM_PROMPT = f"""\
You pick a company's own website from web search results. You are given the company (its name
and what is known about it) and a numbered list of websites, each with the title and text of
the page found there. {UNTRUSTED_RULE}

Return one JSON object and nothing else: {{"n": <the number of the company's own website, or 0>}}
Rules:
- The company's own website is the one it runs itself. A page ABOUT the company on somebody
  else's site (a profile, a news story, a directory, a register, an investor's portfolio page)
  is not it.
- A company is often known by initials, or by a name in its own language, so its website's
  name may be an abbreviation of its name. That is fine when the page text shows it is them.
- A different company with a similar name, or the same name in another country than the one
  described, is not it.
- When no website is clearly theirs, answer 0. A wrong website is worse than none."""


def website_user_prompt(
    name: str, description: str, candidates: Sequence[tuple[str, str, str]]
) -> str:
    """``candidates`` are (domain, page title, page text), numbered from 1 in order."""
    listed = "\n".join(
        f"{n}. {domain}\n   Title: {title or '(none)'}\n   Text: {text[:300] or '(none)'}"
        for n, (domain, title, text) in enumerate(candidates, start=1)
    )
    return (
        f"The company: {untrusted_text(name)}\n"
        f"What is known about it:\n{untrusted_text(description or '(nothing)')}\n\n"
        f"The websites:\n{untrusted_text(listed)}\n\n"
        "Which is the company's own website?"
    )
