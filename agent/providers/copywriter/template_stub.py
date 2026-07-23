"""agent/providers/copywriter/template_stub.py — Deterministic template copywriter.

This is the default copywriter until a real LLM adapter is plugged in (see
llm_copywriter.py). It matches the **style and structure of the existing
rows** in the workbook:
- Greeting to contact.full_name
- Three synergy bullets, driven by config.sender's value propositions
- A short sender-value paragraph, driven by config.sender
- CTA
- signature_name / signature_title from config

Fully generic: no company name is hardcoded anywhere in this file. All
sender identity comes from config.sender (see config/models.py::SenderProfile).
"""

from __future__ import annotations

import textwrap

from agent.domain.models import Company, Contact
from .base import CopyOutput, CopywriterProvider


def _matching_technologies(technologies: tuple[str, ...], description: str) -> list[str]:
    """Return the sender technologies that plausibly overlap with description.

    Case-insensitive word overlap: a technology counts as a match if any of
    its words (longer than 3 characters, to skip "and"/"the"/etc.) appears
    in the target company's description. Deliberately simple — this is the
    template fallback, not the LLM copywriter.
    """
    desc = description.lower()
    hits = []
    for tech in technologies:
        words = [w for w in tech.lower().split() if len(w) > 3]
        if any(w in desc for w in words):
            hits.append(tech)
    return hits


class TemplateCopywriter(CopywriterProvider):
    """Builds copy deterministically from company/contact/sender fields.

    Produces output that matches the structure of the hand-written rows in
    the existing campaign workbook so switching to the LLM adapter won't
    cause formatting drift.
    """

    def write(self, company: Company, contact: Contact, config) -> CopyOutput:  # type: ignore[override]
        s = config.sender
        sig = f"{config.signature_name}\n{config.signature_title}"
        company_description = company.description or f"work in the {company.name} space"
        first_name = contact.full_name.split()[0] if contact.full_name.split() else contact.full_name

        value_props = list(s.value_propositions[:2])
        while len(value_props) < 2:
            value_props.append(
                f"{s.company_name}'s {s.industry or 'platform'} is designed to slot into workflows like yours."
            )

        pitch_email = textwrap.dedent(f"""\
            Hi {first_name},

            My name is {config.signature_name}, {config.signature_title} at {s.company_name}.

            I came across {company.name} and was impressed by {company_description}. I believe there's a compelling opportunity for us to work together.

            Potential synergies:
            • {company.name}'s expertise combined with {s.company_name}'s platform could unlock new gains for both sides.
            • {value_props[0]}
            • {value_props[1]}

            {s.mission or f'At {s.company_name}, we specialize in helping teams like yours make better, faster decisions.'}

            I'd love to schedule a 20-minute call this week to explore whether there's a fit. Would any of the following times work for you?

            Looking forward to connecting.

            {sig}
        """).strip()

        follow_up = textwrap.dedent(f"""\
            Hi {first_name},

            Just following up on my earlier note about a potential partnership between {company.name} and {s.company_name}. I know your time is valuable — I'll be brief.

            We've recently helped comparable teams achieve measurable ROI within the first quarter. I think {company.name} could see similar results.

            Worth a quick 15-minute call? I'm flexible this week.

            {sig}
        """).strip()

        matched = _matching_technologies(s.technologies, company_description)
        commonality_bullets: list[str] = []
        for tech in matched[:2]:
            commonality_bullets.append(f"• Shared focus on {tech}")
        if s.industry:
            commonality_bullets.append(
                f"• {company.name}'s work in {company_description[:80]} aligns with {s.company_name}'s focus on {s.industry}"
            )
        if not commonality_bullets:
            commonality_bullets = [
                f"• Both {company.name} and {s.company_name} operate in adjacent, data-driven domains",
                "• Shared interest in data-driven decision-making",
                f"• {company.name}'s focus on {company_description[:80]} aligns with {s.company_name}'s mission",
            ]

        commonalities = "\n".join(commonality_bullets)

        return CopyOutput(
            pitch_email=pitch_email,
            follow_up=follow_up,
            commonalities=commonalities,
        )
