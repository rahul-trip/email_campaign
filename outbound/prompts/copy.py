"""Prompts for the copy stage: write the five parts of a first email, then check the hook."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from outbound.domain.copy_lint import BANNED_PHRASES
from outbound.prompts.fence import UNTRUSTED_RULE, untrusted_text

ACTOR_SYSTEM_PROMPT = f"""\
You write the first cold email from a salesperson to one named person. You return it in five
parts so a program can assemble it; do not write a greeting, sign-off or footer.

Return one JSON object and nothing else:
{{"hook": "...", "relevance": "...", "value": "...", "ask": "...", "subject": "..."}}

- hook: ONE sentence about something specific to the recipient's company, taken from the
  research notes. It must name a real detail (a product, a launch, a hire, a number).
- relevance: ONE sentence tying that detail to a problem the sender solves.
- value: one or two sentences with a concrete result or proof point from the sender facts.
  Never invent a number, customer or claim that is not in the sender facts.
- ask: exactly ONE question asking for a short conversation. It is the only question mark.
- subject: two to five words, all lower case, no punctuation, no clickbait.

The five parts together must be 48 to 72 words. Use short sentences and plain words (a
12-year-old should follow it). No links. Never use these phrases: {", ".join(BANNED_PHRASES)}.
If earlier drafts by the operator are shown, match the voice of the edited versions.
{UNTRUSTED_RULE}"""

CRITIC_SYSTEM_PROMPT = (
    """\
You check one thing about a cold email: is the opening hook specific to this one company, and
supported by the research notes? A hook is specific if it names something only this company has
said or done. It is generic if it could open an email to any company in the industry, or if the
research notes do not support it.

Return one JSON object and nothing else:
{"specific": true or false, "problem": "<what to change; empty if fine>"}
"""
    + UNTRUSTED_RULE
)


def _list(items: Sequence[str]) -> str:
    return "\n".join(f"- {item}" for item in items if item) or "(none)"


def build_actor_user_prompt(
    *,
    sender: Mapping[str, Any],
    recipient: str,
    title: str,
    company: str,
    research: Mapping[str, Any],
    answers: Mapping[str, str],
    notes: str,
    examples: Sequence[tuple[str, str]],
    feedback: str,
) -> str:
    parts = [
        f"## Sender: {sender.get('company_name', '')}\n{sender.get('narrative', '')}".strip(),
        "## Sender facts you may use\n"
        + _list(
            [
                *map(str, sender.get("value_propositions", [])),
                *map(str, sender.get("case_studies", [])),
            ]
        ),
        f"## Recipient\n{recipient}, {title or 'role unknown'}, at {company}",
        "## Research notes (from the web)\n"
        + untrusted_text(
            f"Summary: {research.get('summary', '')}\n"
            f"Products:\n{_list(research.get('products', []))}\n"
            f"News:\n{_list(research.get('news', []))}\n"
            f"Hook ideas:\n{_list(research.get('hooks', []))}\n"
            f"Hiring: {research.get('hiring', '')}"
        ),
        "## Answers to research questions (from the web)\n"
        + untrusted_text(_list([f"{q}: {a}" for q, a in answers.items() if a])),
        f"## Operator notes about this lead\n{notes or '(none)'}",
    ]
    if examples:
        shown = "\n\n".join(
            f"Engine wrote:\n{generated}\n\nOperator sent:\n{final}"
            for generated, final in examples
        )
        parts.append(f"## Earlier drafts the operator corrected\n{shown}")
    if feedback:
        parts.append(f"## Fix these problems from your last attempt\n{feedback}")
    return "\n\n".join(parts)


def build_critic_user_prompt(company: str, research: Mapping[str, Any], hook: str) -> str:
    return (
        f"## Company\n{company}\n\n## Research notes (from the web)\n"
        + untrusted_text(
            f"Summary: {research.get('summary', '')}\n"
            f"News:\n{_list(research.get('news', []))}\n"
            f"Hook ideas:\n{_list(research.get('hooks', []))}"
        )
        + f"\n\n## Opening hook to check\n{hook}"
    )
