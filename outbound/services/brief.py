"""Drafting a campaign's ideal-customer brief (``outbound.domain.brief``).

One model call reads the campaign (who it is for, the job titles, the research questions) and
the part of the sender profile the writer may use (what they sell, where, to whom). When no
model is set up, or its answer is unusable, a plainer brief is built from those same fields so
discovery still has something to search with. The operator can edit either.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from outbound.domain.brief import Brief
from outbound.domain.discovery import regions
from outbound.domain.entities import Campaign
from outbound.logging import get_logger
from outbound.prompts.brief import SYSTEM_PROMPT, user_prompt
from outbound.providers.errors import ProviderError
from outbound.providers.llm_json import parse_json_object
from outbound.providers.ports import LlmClient

log = get_logger(__name__)


def draft_brief(llm: LlmClient | None, *, campaign: Campaign, profile: Mapping[str, Any]) -> Brief:
    if llm is not None:
        try:
            reply = llm.complete(
                SYSTEM_PROMPT,
                user_prompt(campaign, profile),
                json_mode=True,
                temperature=0.2,
                max_tokens=1_200,
            )
            brief = Brief.from_json(parse_json_object(llm.name, reply.text))
            if not brief.is_empty:
                return brief
        except ProviderError as error:
            log.warning("brief_drafting_failed", reason=str(error)[:200])
    return fallback_brief(campaign, profile)


def fallback_brief(campaign: Campaign, profile: Mapping[str, Any]) -> Brief:
    """What is known without a model: the description, the regions and industries sold to."""
    return Brief.from_json(
        {
            "summary": campaign.icp_description or str(profile.get("narrative") or ""),
            "regions": regions(profile),
            "segments": list(profile.get("target_verticals") or []),
        }
    )
