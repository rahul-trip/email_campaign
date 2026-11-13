"""The prompt for drafting a campaign's ideal-customer brief (``outbound.domain.brief``)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from outbound.domain.entities import Campaign
from outbound.prompts.fence import UNTRUSTED_RULE, untrusted_text

SYSTEM_PROMPT = f"""\
You write the brief that says which companies a salesperson should look for. You are given the
seller (what they sell, to whom and where) and the campaign (who it is for, the job titles it
writes to, the questions it wants answered). {UNTRUSTED_RULE}

The brief describes the BUYER, never the seller: companies that would buy what the seller
sells. A company that sells the same thing as the seller is a competitor, so list it under
disqualifiers. So is a company that only sells software, data or services to those buyers
without being one of them (a vendor to the same market): list "vendor to <the buyers>, not
one of them" under disqualifiers too.

Return one JSON object and nothing else:
{{"summary": "<two or three sentences: who the ideal customer is and why they buy>",
"company_type": "startup" | "sme" | "enterprise" | "public_sector" | "any",
"keywords": ["<market, product or technology terms that describe what THESE companies do>"],
"segments": ["<kinds of company, e.g. 'B2B SaaS start-ups', 'regional utilities'>"],
"regions": ["<countries or regions, as the seller states them>"],
"size_range": "<e.g. '10-200 employees', or empty>",
"founded_after": <year or null>,
"funding_stages": ["<e.g. 'seed', 'series A'; empty unless start-ups>"],
"industry_codes": ["<UK SIC 2007 codes, five digits, that such companies register under>"],
"must_haves": [{{"text": "<a condition a company must meet>", "weight": 1 | 2 | 3}}],
"disqualifiers": ["<a condition that rules a company out, e.g. 'competitor: ...'>"],
"buying_signals": ["<an event that makes them likely to buy now, e.g. 'recent funding'>"],
"source_hints": ["<kinds of page that list many such companies, e.g. 'accelerator cohorts',
'funding round-ups', 'industry association members', 'award shortlists'>"],
"seed_companies": ["<websites of real example customers the text names; never invent one>"]}}
Rules:
- Use only what the text supports. Leave a field empty rather than guess.
- At most eight items in each list, each a few plain words.
- Weight 3 for what is essential, 1 for what is merely good to have."""

_PROFILE_FIELDS = (
    ("Company", "company_name"),
    ("Industry", "industry"),
    ("Mission", "mission"),
    ("Sells in", "geographic_focus"),
    ("Value propositions", "value_propositions"),
    ("Proof points", "case_studies"),
    ("Technologies", "technologies"),
    ("Sells to", "target_verticals"),
    ("About them", "narrative"),
)


def user_prompt(campaign: Campaign, profile: Mapping[str, Any]) -> str:
    def field(value: object) -> str:
        if isinstance(value, list | tuple):
            return "; ".join(str(v) for v in value[:10])
        return str(value or "")[:1_500]

    seller = "\n".join(
        f"{label}: {field(profile.get(key))}"
        for label, key in _PROFILE_FIELDS
        if field(profile.get(key))
    )
    wanted = "\n".join(
        line
        for line in (
            f"Who it is for: {campaign.icp_description or ''}",
            f"Job titles it writes to: {field(campaign.target_titles)}",
            f"Questions it wants answered: {field(campaign.research_questions)}",
        )
        if not line.endswith(": ")
    )
    return (
        f"The seller:\n{untrusted_text(seller)}\n\n"
        f"The campaign:\n{untrusted_text(wanted)}\n\n"
        "Write the brief."
    )
