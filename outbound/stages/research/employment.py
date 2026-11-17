"""Settling who works at the company: free rules first, one model call for the rest.

The rules (``domain.placement``) place the clear cases. What is left goes to the model in one
batch per lead, which reads each person's public headline and snippet and may only say that
someone works elsewhere when the text says so; anything else stays ``UNSURE`` for the operator.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from outbound.domain.placement import Placement
from outbound.logging import get_logger
from outbound.prompts import research as prompts
from outbound.providers.errors import BudgetExceeded, ProviderError
from outbound.providers.llm_json import ask_json as ask
from outbound.providers.ports import LlmClient

log = get_logger(__name__)
EXTRACTION_TEMPERATURE = 0.2


@dataclass(frozen=True)
class Candidate:
    """A person whose place the rules could not settle, with what the search showed of them."""

    name: str
    evidence: str


class _Verdict(BaseModel):
    model_config = ConfigDict(extra="ignore")
    n: int = 0
    verdict: str = ""
    reason: str = ""


class _Verdicts(BaseModel):
    model_config = ConfigDict(extra="ignore")
    people: list[_Verdict] = Field(default_factory=list)


def judge_people(
    llm: LlmClient, company: str, domain: str, summary: str, people: Sequence[Candidate]
) -> list[tuple[Placement, str]]:
    """A verdict per person, in order. Anything missing, or any failure, is ``UNSURE``."""
    unsure = (Placement.UNSURE, "the profile does not clearly say where they work")
    if not people:
        return []
    listing = "\n".join(f"{i}. {p.name}: {p.evidence[:400]}" for i, p in enumerate(people, 1))
    try:
        reply = ask(
            llm,
            prompts.EMPLOYMENT_SYSTEM_PROMPT,
            prompts.build_employment_user_prompt(company, domain, summary, listing),
            _Verdicts,
            temperature=EXTRACTION_TEMPERATURE,
        )
    except BudgetExceeded:
        raise
    except ProviderError as error:
        log.warning("employment_check_failed", reason=str(error)[:200])
        return [unsure] * len(people)
    out = [unsure] * len(people)
    for item in reply.people:
        if 1 <= item.n <= len(people) and item.verdict in {p.value for p in Placement}:
            reason = " ".join(item.reason.split())[:300] or unsure[1]
            out[item.n - 1] = (Placement(item.verdict), reason)
    return out
