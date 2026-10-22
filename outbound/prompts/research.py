"""Prompts for the research stage: read a company's pages, answer questions, score the fit."""

from __future__ import annotations

from collections.abc import Sequence

from outbound.prompts.fence import UNTRUSTED_RULE, untrusted_text

_JSON_ONLY = "Reply with one JSON object and nothing else: no commentary, no code fences."
_GROUNDED = (
    "Use only the text provided. If the text does not say, leave the field empty rather than "
    "guessing. Never invent people, numbers or news. " + UNTRUSTED_RULE
)

SITE_SYSTEM_PROMPT = f"""\
You read a company's own web pages and report what a salesperson needs before writing to them.
{_GROUNDED}

Return: {{"sector": "<the market they work in, two to five words, e.g. 'wind power forecasting'>",
"company_name": "<the name the company calls itself on these pages, e.g. 'Amperon'
or 'LTIMindtree'; never a page title, headline or slogan; empty if the pages do not say>",
"summary": "<2-3 sentences: what the company does and for whom>",
"products": ["<product or service>", ...],
"news": ["<recent, specific, dated if the text dates it>", ...],
"hooks": ["<a concrete, specific thing worth mentioning in a first email>", ...]}}
At most 5 products, 3 news items and 3 hooks. A hook must be something only this company
would have said or done. {_JSON_ONLY}"""

SIGNALS_SYSTEM_PROMPT = f"""\
You answer a salesperson's research questions about one company, and note hiring and
technology signals. {_GROUNDED}

Return: {{"answers": {{"<question exactly as asked>": "<short answer, or empty string>"}},
"hiring": "<what the careers text or search results show about hiring, or empty>",
"tech": ["<technology or tool the company is shown to use>", ...]}}
{_JSON_ONLY}"""

PERSONA_SYSTEM_PROMPT = f"""\
You extract the people listed on a company's team, leadership or about page.
{_GROUNDED} Only people who work at this company: leave out customers, partners, investors,
authors of quoted articles and anyone the text does not place at the company.

Return: {{"people": [{{"name": "<full name>", "title": "<job title>",
"linkedin_url": "<profile URL if the text gives one, else empty>"}}, ...]}}
At most 10 people, most senior first. {_JSON_ONLY}"""

NEWS_SYSTEM_PROMPT = f"""\
You pick the news worth opening a first email to one company with. You are given numbered
search results in two lists: news about the company itself, and news about its market.
{_GROUNDED}

Return: {{"company": [{{"n": <number>, "detail": "<one sentence: what happened, from the result
text only>"}}, ...],
"market": [{{"n": <number>, "detail": "<one sentence: what happened>",
"matters": "<one sentence: why it matters to this company>"}}, ...]}}
- "company": only results that are about THIS company (it is named, or clearly the subject).
  Leave out results that merely mention it in a list, and anything that is a press-release
  boilerplate, a job ad, a stock price or a directory listing. At most 3, best first.
- "market": only results about regulation, tenders, funding, acquisitions or market moves that a
  company like this one would care about. At most 2, best first.
- Use only the numbers you were given. Empty lists are a good answer. {_JSON_ONLY}"""

FIT_SYSTEM_PROMPT = f"""\
You judge how well a company matches a seller's ideal customer, from 0 (no match) to 100
(exactly the target). Be strict: 80 or more means you would put them at the top of the list.
{_GROUNDED}

Return: {{"score": <integer 0-100>, "reason": "<one sentence naming the deciding factor>"}}
{_JSON_ONLY}"""


def _block(title: str, body: str) -> str:
    return f"## {title}\n{body.strip() or '(nothing)'}\n"


def untrusted(title: str, body: str) -> str:
    return f"## {title}\n{untrusted_text(body)}\n"


def build_site_user_prompt(company: str, domain: str, pages: str) -> str:
    return _block("Company", f"{company} ({domain})") + untrusted("Pages", pages)


def build_signals_user_prompt(
    company: str, questions: Sequence[str], pages: str, search_snippets: str
) -> str:
    asked = "\n".join(f"- {q}" for q in questions)
    return (
        _block("Company", company)
        + _block("Questions", asked)
        + untrusted("Pages", pages)
        + untrusted("Search results (hiring, technology)", search_snippets)
    )


def build_news_user_prompt(
    company: str, sector: str, summary: str, company_hits: str, market_hits: str
) -> str:
    return (
        _block("Company", f"{company}: {summary}" if summary else company)
        + _block("Their market", sector)
        + untrusted("News about the company", company_hits)
        + untrusted("News about their market", market_hits)
    )


def build_persona_user_prompt(company: str, team_text: str) -> str:
    return _block("Company", company) + untrusted("Team text", team_text)


def build_fit_user_prompt(
    icp: str, company: str, summary: str, products: Sequence[str], notes: str, answers: str
) -> str:
    return (
        _block("Ideal customer", icp)
        + _block("Company", company)
        + untrusted("What they do", summary)
        + untrusted("Products", "\n".join(f"- {p}" for p in products))
        + _block("Operator notes", notes)
        + untrusted("Answers to research questions", answers)
    )
