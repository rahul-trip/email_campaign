"""Suggestions for a new workspace's profile and campaign (onboarding).

Nothing here saves a profile or a campaign: it returns what the model read, and the person
checks, corrects and confirms it (``SettingsService.update_sender_profile`` sets
``reviewed_at``, never this). The only write is one ``profile_drafted`` event, which is also
how the daily limit is counted. A missing model or search provider, an unreadable site or an
unusable answer is a result (``drafted=False`` and a reason), not an error: the screen then
shows the blank form it always had.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from outbound.db.types import utcnow
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.actors import OPERATOR
from outbound.domain.domains import registrable_domain
from outbound.domain.enums import EntityType
from outbound.logging import get_logger
from outbound.prompts.setup import (
    CAMPAIGN_SYSTEM_PROMPT,
    PROFILE_SYSTEM_PROMPT,
    campaign_user_prompt,
    profile_user_prompt,
)
from outbound.providers.errors import ProviderError
from outbound.providers.llm_json import ask_json
from outbound.providers.ports import LlmClient, SearchProvider

log = get_logger(__name__)

PAGE_PATHS = ("", "/about", "/contact", "/customers", "/products")  # five URLs = one extract credit
DAILY_LIMIT = 5
EVENT = "profile_drafted"
ITEM_CHARS = 200
# The same limits as ``SenderProfileIn``.
_TEXT = {
    "company_name": 200, "industry": 200, "mission": 1000, "geographic_focus": 500,
    "narrative": 8000, "legal_name": 300, "postal_address": 500, "registration_details": 500,
    "contact_info": 500,
}  # fmt: skip
_LISTS = {"value_propositions": 6, "case_studies": 6, "technologies": 8, "target_verticals": 8}


class _Reply(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ProfileReply(_Reply):
    company_name: str = ""
    industry: str = ""
    mission: str = ""
    geographic_focus: str = ""
    narrative: str = ""
    legal_name: str = ""
    postal_address: str = ""
    registration_details: str = ""
    contact_info: str = ""
    value_propositions: list[str] = Field(default_factory=list)
    case_studies: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    target_verticals: list[str] = Field(default_factory=list)


class CampaignReply(_Reply):
    target_titles: list[str] = Field(default_factory=list)
    icp_description: str = ""
    research_questions: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class ProfileDraft:
    drafted: bool
    reason: (
        str | None
    )  # no_model, no_search, bad_website, site_unreadable, model_failed, daily_limit
    fields: dict[str, Any]
    pages: tuple[str, ...]


@dataclass(frozen=True)
class CampaignDraft:
    drafted: bool
    reason: str | None  # no_model, profile_empty, model_failed
    target_titles: tuple[str, ...] = ()
    icp_description: str = ""
    research_questions: tuple[str, ...] = ()


def _items(values: list[str], limit: int) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        text = str(value).strip()[:ITEM_CHARS]
        if text:
            seen.setdefault(text)
    return list(seen)[:limit]


class SetupDrafts:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        workspace_id: str,
        *,
        search: SearchProvider | None,
        llm: LlmClient | None,
        actor: str = OPERATOR,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._uow = uow_factory
        self._workspace_id = workspace_id
        self._search = search
        self._llm = llm
        self._actor = actor
        self._now = now

    def profile(self, website: str) -> ProfileDraft:
        def no(reason: str) -> ProfileDraft:
            return ProfileDraft(False, reason, {}, ())

        with self._uow(self._workspace_id) as uow:
            workspace = uow.workspace()
            saved = str(workspace.sender_profile.get("domain") or "") if workspace else ""
            recent = uow.events.latest(EntityType.WORKSPACE, self._workspace_id, EVENT, DAILY_LIMIT)
        domain = registrable_domain(website) if website.strip() else registrable_domain(saved)
        if not domain:
            return no("bad_website")
        if self._llm is None:
            return no("no_model")
        if self._search is None:
            return no("no_search")
        if len(recent) >= DAILY_LIMIT and self._now() - recent[0].created_at < timedelta(hours=24):
            return no("daily_limit")

        try:  # no transaction is open while the network is used
            extracted = self._search.extract([f"https://{domain}{p}" for p in PAGE_PATHS])
        except ProviderError as error:
            log.warning("profile_draft_failed", step="pages", reason=str(error)[:200])
            return no("site_unreadable")
        pages = {p.url: p.text for p in extracted if p.text.strip()}
        if not pages:
            return no("site_unreadable")
        try:
            reply = ask_json(
                self._llm,
                PROFILE_SYSTEM_PROMPT,
                profile_user_prompt(domain, pages),
                ProfileReply,
                temperature=0.2,
            )
        except ProviderError as error:
            log.warning("profile_draft_failed", step="model", reason=str(error)[:200])
            return no("model_failed")

        fields: dict[str, Any] = {}
        for key, limit in _TEXT.items():
            value = str(getattr(reply, key)).strip()[:limit]
            if value:
                fields[key] = value
        for key, limit in _LISTS.items():
            items = _items(getattr(reply, key), limit)
            if items:
                fields[key] = items
        fields["domain"] = domain  # ours, never the model's

        with self._uow(self._workspace_id) as uow:
            uow.events.append(
                EntityType.WORKSPACE,
                self._workspace_id,
                EVENT,
                self._actor,
                {"domain": domain, "pages": len(pages), "fields": sorted(fields)},
            )
            uow.commit()
        log.info("profile_drafted", pages=len(pages), fields=len(fields))
        return ProfileDraft(True, None, fields, tuple(pages))

    def campaign(self) -> CampaignDraft:
        with self._uow(self._workspace_id) as uow:
            workspace = uow.workspace()
            profile = dict(workspace.sender_profile) if workspace else {}
        if not any(
            profile.get(k) for k in ("narrative", "value_propositions", "industry", "mission")
        ):
            return CampaignDraft(False, "profile_empty")
        if self._llm is None:
            return CampaignDraft(False, "no_model")
        try:
            reply = ask_json(
                self._llm,
                CAMPAIGN_SYSTEM_PROMPT,
                campaign_user_prompt(profile),
                CampaignReply,
                temperature=0.2,
            )
        except ProviderError as error:
            log.warning("campaign_draft_failed", reason=str(error)[:200])
            return CampaignDraft(False, "model_failed")
        return CampaignDraft(
            True,
            None,
            tuple(_items(reply.target_titles, 6)),
            reply.icp_description.strip()[:1000],
            tuple(_items(reply.research_questions, 3)),
        )
