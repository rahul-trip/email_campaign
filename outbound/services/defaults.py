"""Starting values for a new workspace. Edit them in the app afterwards; creating a workspace
never overwrites what is already there.

A new workspace starts **empty**: the company's name and website, and nothing else. What the
writer may say about the company, who signs, the legal footer and the ideal customer are all
written by the customer and confirmed before any email is drafted (the copy stage refuses until
the profile is confirmed). Never ship claims, numbers or another company's wording as defaults.
"""

from __future__ import annotations

from typing import Any

DEFAULT_WORKSPACE_NAME = "default"
DEFAULT_CAMPAIGN_NAME = "default"


def blank_sender_profile(company_name: str = "", website: str = "") -> dict[str, Any]:
    """The profile of a workspace that has not set itself up yet."""
    return {
        "company_name": company_name.strip(),
        "domain": website.strip(),
        "industry": "",
        "mission": "",
        "value_propositions": [],
        "technologies": [],
        "target_verticals": [],
        "case_studies": [],
        # How the emails are written: how they open, what you want from them, and emails you
        # have sent that show your voice (reference only; see the copy prompt).
        "greeting": "Hi",
        "outreach_goal": "",
        "style_examples": [],
        "geographic_focus": "",
        "signature_name": "",
        "signature_title": "",
        # Needed by the country footers. Fill these in before drafting.
        "legal_name": "",
        "postal_address": "",
        "registration_details": "",
        "contact_info": "",
        "narrative": "",
    }


def default_workspace_settings() -> dict[str, Any]:
    return {
        "send_enabled": False,  # automatic sending stays off until Phase 5's gate passes
        "safe_to_send_only": True,
        "budget_per_prospect_micro_usd": 500_000,  # the $0.50 ceiling
        "breaker": {"hard_per_100": 3, "hard_per_24h": 2},
        "catch_all_resolver": "scrubby",
        "reply_webhook_url": None,
        "few_shot_examples": 5,
        "timezone": "UTC",
        "country_policy_enabled": True,
        "footer_enabled": True,
        "email_min_words": 120,  # the first email's length, set under Settings → Limits
        "email_max_words": 200,
    }
