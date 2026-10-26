"""The prompt for planning searches that find new companies to write to."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from outbound.prompts.fence import UNTRUSTED_RULE, untrusted_text

SYSTEM_PROMPT = f"""\
You plan web searches that find companies a salesperson should write to. You are given the
seller (what they sell and where), the ideal customer, and the searches already
run. {UNTRUSTED_RULE}

Return one JSON object and nothing else: {{"queries": ["<search>", ...]}}.
Rules:
- Each search must find COMPANY websites that fit the ideal customer, not news, reports or blogs.
- Every search takes a different angle from the searches already run and from each other: a
  region, a kind or size of company, a technology they use, or a recent signal such as an
  announced project, a tender, funding or hiring.
- Stay relevant to what the seller sells. Stay inside the seller's regions and industries when
  they are given. Never drift to companies the seller could not help.
- Plain words a search engine understands, under 20 words each. No quotation marks or operators.
- Never repeat a search already run, and never reword one."""


def user_prompt(profile: Mapping[str, Any], icp: str, used: Sequence[str], count: int) -> str:
    def field(name: str) -> str:
        value = profile.get(name)
        if isinstance(value, list):
            return ", ".join(str(v) for v in value[:8])
        return str(value or "")[:600]

    seller = "\n".join(
        f"{label}: {field(key)}"
        for label, key in (
            ("Company", "company_name"),
            ("Industry", "industry"),
            ("Mission", "mission"),
            ("What they do", "narrative"),
            ("Value", "value_propositions"),
            ("Technologies", "technologies"),
            ("Sells in", "geographic_focus"),
            ("Sells to", "target_verticals"),
        )
        if field(key)
    )
    earlier = "\n".join(f"- {q}" for q in used[-20:]) or "(none yet)"
    return (
        f"The seller:\n{untrusted_text(seller)}\n\n"
        f"The ideal customer:\n{untrusted_text(icp)}\n\n"
        f"Searches already run:\n{earlier}\n\n"
        f"Write {count} new searches."
    )
