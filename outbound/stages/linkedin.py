"""Writing the LinkedIn drafts for a lead's confirmed people. Plain Python, no graph.

One call writes the connection note and the follow-up for every person at a lead; each pair is
checked (``domain.linkedin.lint_linkedin``) and one more call rewrites only those that break a
rule. A draft that still
breaks one is kept with its issues, so the operator sees them and edits it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from outbound.domain.linkedin import lint_linkedin
from outbound.prompts import linkedin as prompts
from outbound.providers.errors import ProviderError
from outbound.providers.llm_json import ask_json as ask
from outbound.providers.ports import LlmClient


class _Draft(BaseModel):
    model_config = ConfigDict(extra="ignore")
    n: int = 0
    note: str = ""
    message: str = ""


class _Drafts(BaseModel):
    model_config = ConfigDict(extra="ignore")
    drafts: list[_Draft] = Field(default_factory=list)


@dataclass(frozen=True)
class LinkedInLead:
    """What is shared by everyone at one lead: who writes, about which company."""

    sender: Mapping[str, Any]
    company_name: str
    research: Mapping[str, Any]
    notes: str = ""


@dataclass(frozen=True)
class LinkedInInput:
    sender: Mapping[str, Any]
    first_name: str
    title: str
    company_name: str
    research: Mapping[str, Any]
    notes: str = ""


@dataclass(frozen=True)
class LinkedInDraft:
    note: str
    message: str
    issues: tuple[str, ...]


def _clean(text: str) -> str:
    return "\n".join(" ".join(line.split()) for line in text.strip().splitlines())


def write_linkedin(llm: LlmClient, inp: LinkedInInput) -> LinkedInDraft:
    """One person's pair (the lead page's Write and Rewrite)."""
    lead = LinkedInLead(inp.sender, inp.company_name, inp.research, inp.notes)
    (draft,) = write_linkedin_many(llm, lead, [(inp.first_name, inp.title)])
    if draft is None:
        raise ProviderError(llm.name, "the reply had no draft for this person")
    return draft


def write_linkedin_many(
    llm: LlmClient, lead: LinkedInLead, recipients: Sequence[tuple[str, str]]
) -> list[LinkedInDraft | None]:
    """A pair for each (first name, title) at one lead, in one model call; then one more call
    rewrites only the pairs the checks object to. ``None`` for a recipient the replies left out.
    """
    if not recipients:
        return []
    out: list[LinkedInDraft | None] = [None] * len(recipients)
    rewrites: dict[int, tuple[str, str, str]] = {}
    for attempt in range(2):  # every draft at once, then one rewrite of those that failed
        reply = ask(
            llm,
            prompts.LINKEDIN_SYSTEM_PROMPT,
            prompts.build_linkedin_user_prompt(
                sender=lead.sender,
                recipients=recipients,
                company=lead.company_name,
                research=lead.research,
                notes=lead.notes,
                rewrites=rewrites or None,
            ),
            _Drafts,
        )
        asked = set(rewrites) if rewrites else set(range(1, len(recipients) + 1))
        rewrites = {}
        for item in reply.drafts:
            if item.n not in asked:
                continue
            note, message = _clean(item.note), _clean(item.message)
            issues = lint_linkedin(note, message)
            out[item.n - 1] = LinkedInDraft(note, message, tuple(issues))
            if issues and attempt == 0:
                rewrites[item.n] = (note, message, prompts.feedback_for(issues))
        missing = [n for n in asked if out[n - 1] is None]
        if attempt == 0:
            for n in missing:  # left out of the reply: asked again with the rewrites
                rewrites[n] = ("", "", "- write this recipient's pair")
        if not rewrites:
            break
    return out
