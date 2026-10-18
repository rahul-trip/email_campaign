"""Starting values for a new workspace. Edit them in the database afterwards; seeding never
overwrites what is already there.

The sender profile is ported from the legacy ``agent/`` examples. The legal name, postal address
and registration details are blank on purpose: they must be filled in before any email is
drafted, because the country footers need them.
"""

from __future__ import annotations

from typing import Any

DEFAULT_WORKSPACE_NAME = "default"
DEFAULT_CAMPAIGN_NAME = "default"

DEFAULT_TARGET_TITLES = ["VP of Sales", "CTO", "Chief Architect", "Director of Product"]

DEFAULT_ICP = (
    "Utilities, energy retailers, grid operators and trading desks that manage volatile "
    "renewable assets and need forecasts that plug into live operational decisions."
)

_NARRATIVE = """\
Quantra Energy is an AI-driven forecasting company serving utilities, retailers, and grid
operators. We build machine-learning models for short-term renewable generation and demand
forecasting, then plug them directly into a customer's existing dispatch, trading, or
grid-operations workflows, with no rip-and-replace.

Key differentiators:
- Deployed and proven with prominent Indian and US-based energy utilities navigating volatile
  renewable assets.
- Forecasts are built for operational use (dispatch, trading desks), not just reporting.
- Fast integration: designed to slot into a customer's stack in days, not months.

Proof points: reduced forecast error by 20-35% for utility and trading-desk customers,
directly improving dispatch accuracy and P&L.

Overlap keywords: machine learning, renewable forecasting, solar nowcasting, grid
optimization, dispatch algorithms, carbon-aware dispatch, demand forecasting, real-time
operational data, high-resolution meteorological data.
"""


def default_sender_profile() -> dict[str, Any]:
    return {
        "company_name": "Quantra Energy",
        "domain": "quantraenergy.com",
        "industry": "Energy & Renewables Analytics",
        "mission": "AI-driven intelligence for energy-sector decision-making",
        "value_propositions": [
            "Renewable grid analytics that slot into existing workflows, cutting integration "
            "from months to days",
            "Energy-forecast error reduction of 20-35%, improving trading desk P&L",
        ],
        "technologies": [
            "machine learning",
            "renewable forecasting",
            "grid optimization",
            "dispatch algorithms",
        ],
        "target_verticals": ["Grid operators", "Energy trading desks"],
        "case_studies": [
            "Reduced forecast error 30% for a UK energy trader: GBP 2M annual P&L uplift"
        ],
        "geographic_focus": "UK, Europe, India",
        "signature_name": "[Your Name]",
        "signature_title": "CPO & Founder",
        # Needed by the country footers. Fill these in before drafting.
        "legal_name": "",
        "postal_address": "",
        "registration_details": "",
        "contact_info": "",
        "narrative": _NARRATIVE,
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
    }
