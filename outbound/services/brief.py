"""Drafting a campaign's ideal-customer brief (``outbound.domain.brief``).

One model call reads the campaign (who it is for, the job titles, the research questions) and
the part of the sender profile the writer may use (what they sell, where, to whom). When no
model is set up, or its answer is unusable, a plainer brief is built from those same fields so
discovery still has something to search with. The operator can edit either.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from outbound.domain.brief import Brief
from outbound.domain.discovery import regions
from outbound.domain.entities import Campaign
from outbound.logging import get_logger
from outbound.prompts.brief import SYSTEM_PROMPT, user_prompt
from outbound.providers.errors import ProviderError
from outbound.providers.llm_json import ask_object
from outbound.providers.ports import LlmClient

log = get_logger(__name__)


@dataclass(frozen=True)
class Drafted:
    brief: Brief
    fell_back: bool  # the plain fallback was built: no model, or its answer was unusable


def draft(llm: LlmClient | None, *, campaign: Campaign, profile: Mapping[str, Any]) -> Drafted:
    if llm is not None:
        try:
            reply = ask_object(llm, SYSTEM_PROMPT, user_prompt(campaign, profile), temperature=0.2)
            brief = Brief.from_json(reply)
            if not brief.is_empty:
                return Drafted(brief, fell_back=False)
        except ProviderError as error:
            log.warning("brief_drafting_failed", reason=str(error)[:200])
    return Drafted(fallback_brief(campaign, profile), fell_back=True)


def draft_brief(llm: LlmClient | None, *, campaign: Campaign, profile: Mapping[str, Any]) -> Brief:
    return draft(llm, campaign=campaign, profile=profile).brief


def fallback_brief(campaign: Campaign, profile: Mapping[str, Any]) -> Brief:
    """What is known without a model: the description, the regions and industries sold to."""
    return Brief.from_json(
        {
            "summary": campaign.icp_description or str(profile.get("narrative") or ""),
            "regions": regions(profile),
            "segments": list(profile.get("target_verticals") or []),
        }
    )
