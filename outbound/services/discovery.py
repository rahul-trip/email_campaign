"""Planning which searches to run when looking for new companies.

Each run asks a model for a few new angles on the campaign's ideal customer, given what the
sender sells and where, and what was already searched. If no model is set up, or its answer is
unusable, fixed angles are used instead (``outbound.domain.discovery``). Whatever is run is
remembered as an event, so the next run does not repeat it. The model is metered like every
other paid call.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from outbound.domain.discovery import clean, fallback_queries, normal
from outbound.logging import get_logger
from outbound.prompts.discovery import SYSTEM_PROMPT, user_prompt
from outbound.providers.errors import ProviderError
from outbound.providers.llm_json import parse_json_object
from outbound.providers.ports import LlmClient

log = get_logger(__name__)

HISTORY = 30  # how many earlier searches a run remembers and avoids


def plan_queries(
    *,
    llm: LlmClient | None,
    base: str,
    profile: Mapping[str, Any],
    icp: str,
    used: Sequence[str],
    count: int,
) -> list[str]:
    """Up to ``count`` searches not run before. The plain search for the ideal customer comes
    first the first time; after that every run takes new angles."""
    queries: list[str] = []
    if normal(base) not in {normal(q) for q in used}:
        queries.append(base)
    want = count - len(queries)
    if want > 0 and llm is not None:
        try:
            reply = llm.complete(
                SYSTEM_PROMPT,
                user_prompt(profile, icp, used, want),
                json_mode=True,
                temperature=0.9,  # new angles, not the same ones again
                max_tokens=600,
            )
            planned = parse_json_object(llm.name, reply.text).get("queries", [])
            queries += clean(
                planned if isinstance(planned, list) else [], used=[*used, *queries], limit=want
            )
        except ProviderError as error:
            log.warning("discovery_planning_failed", reason=str(error)[:200])
    if len(queries) < count:  # no model, or too few usable: fixed angles fill the rest
        queries += fallback_queries(
            base, profile, used=[*used, *queries], limit=count - len(queries)
        )
    return queries
