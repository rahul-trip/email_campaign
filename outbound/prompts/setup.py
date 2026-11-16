"""Prompts that suggest a new workspace's profile and campaign (``services.setup_draft``).

Both only suggest: the person reads, corrects and confirms before anything is saved.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from outbound.prompts.brief import PROFILE_FIELDS
from outbound.prompts.fence import UNTRUSTED_RULE, untrusted_text

PROFILE_SYSTEM_PROMPT = f"""\
You read a seller's own website and fill in their company profile. {UNTRUSTED_RULE}

Everything you write will be shown to the seller to check, and may later be quoted in emails
sent under their name. So:
- Use only what the pages state. Leave a field empty ("" or []) rather than guess.
- A proof point is a customer, number or result the pages themselves show. Never invent one.
- Copy the legal name, postal address and registration details only if a page prints them
  (usually the footer, contact or imprint page). Never build an address from a city name.
- Write in plain words, as the seller would say it to a customer. No slogans.

Return one JSON object and nothing else:
{{"company_name": "<as the site writes it>",
"industry": "<a few words>",
"mission": "<one sentence, or empty>",
"geographic_focus": "<where they sell, as the site says, or empty>",
"value_propositions": ["<what they offer, one short line each, at most 6>"],
"case_studies": ["<a proof point the site shows, at most 6>"],
"technologies": ["<technologies the site names, at most 8>"],
"target_verticals": ["<kinds of customer the site says it serves, at most 8>"],
"narrative": "<three to five sentences: what they do, for whom, what sets them apart>",
"legal_name": "", "postal_address": "", "registration_details": "", "contact_info": ""}}"""

CAMPAIGN_SYSTEM_PROMPT = f"""\
You suggest who a seller should write to. You are given the seller's own profile. {UNTRUSTED_RULE}

Describe the BUYER, never the seller.
Return one JSON object and nothing else:
{{"target_titles": ["<job titles of the people who decide to buy this, best first, at most 6>"],
"icp_description": "<two or three plain sentences: what kind of company buys it, size, where>",
"research_questions": ["<a question whose answer makes an email to them specific, at most 3>"]}}
Rules:
- Job titles are jobs a person holds ("Head of Trading"), never departments or company types.
- Use only what the profile supports. Leave a field empty rather than guess."""

PAGE_CHARS = 6_000
TOTAL_CHARS = 24_000


def profile_user_prompt(domain: str, pages: Mapping[str, str]) -> str:
    parts: list[str] = []
    used = 0
    for url, text in pages.items():
        chunk = f"--- {url}\n{text.strip()[:PAGE_CHARS]}"
        if used + len(chunk) > TOTAL_CHARS:
            break
        parts.append(chunk)
        used += len(chunk)
    return f"The website {domain}:\n{untrusted_text(chr(10).join(parts))}\n\nFill in the profile."


def campaign_user_prompt(profile: Mapping[str, Any]) -> str:
    def field(value: object) -> str:
        if isinstance(value, list | tuple):
            return "; ".join(str(v) for v in value[:10])
        return str(value or "")[:1_500]

    seller = "\n".join(
        f"{label}: {field(profile.get(key))}"
        for label, key in PROFILE_FIELDS
        if field(profile.get(key))
    )
    return f"The seller:\n{untrusted_text(seller)}\n\nSuggest who to write to."
