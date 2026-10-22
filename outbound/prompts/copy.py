"""Prompts for the copy stage: write a first email the way a person would, then check it."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from outbound.prompts.fence import UNTRUSTED_RULE, untrusted_text

# Shown to the writer with the operator's own past emails, which are reference material, not a
# template: they are the voice and substance the operator wants, but they read as written by a
# model (stock opening, bullet lists, "synergies").
STYLE_EXAMPLES_NOTE = (
    "Emails the operator has sent before. Use them for what the operator offers and how direct"
    " they want to be. They read as templated, so do NOT copy their wording, greeting, opening"
    " paragraph or bullet lists."
)


def actor_system_prompt(min_words: int, max_words: int) -> str:
    return f"""\
You write the first email from one person at a company to one named person at another. It
must read the way a thoughtful senior person types to a peer: specific, plain and a little
informal. It must not read like marketing copy, and it must not read like AI.

Return one JSON object and nothing else:
{{"subject": "...", "body": "...", "based_on": "..."}}

body: the paragraphs only, with a blank line between them. Do not write a greeting, sign-off,
signature or footer: a program adds those.

How to write the body
1. Open with something that happened. Use the most recent dated item in the research notes:
   first news about their company, else a market development that affects them, else the most
   specific fact from their own site. State it plainly, in your own words, with its timing
   ("last month", "this week"). Do not pretend site content is news.
2. Say what you make of it for them, in one or two sentences. Give a view; do not praise them.
3. Say what the sender does or has done that bears on it, in plain terms. Use only the sender
   facts. One concrete thing beats a list of capabilities.
4. End with one clear, low-pressure ask that fits the sender's goal, as a question they can
   answer in a line.

Voice
- 2 to 4 short paragraphs, {min_words} to {max_words} words in all.
- Write the way you talk: contractions, sentences of different lengths, "I" and "we".
- No bullet points, numbered lists, bold or headings.
- No flattery ("impressive", "admire", "excellent track record") and no hype words (leading,
  seamless, robust, cutting-edge, innovative, powerful, strategic, synergies).
- Do not say "I hope this finds you well", "reaching out", "I came across", "caught my eye".
- At most one em dash. No links. No email addresses.
- Never invent a number, customer, event, date or claim. Every fact about them must be in the
  research notes; every fact about the sender must be in the sender facts.

subject: two to six words, lower case, no punctuation, about their news or topic, nothing
clickbait.
based_on: the url of the news item you opened with, copied exactly from the research notes, or
an empty string if you opened with a fact from their site.

If earlier emails by the operator are shown with their corrections, match the voice of the
corrected versions. {UNTRUSTED_RULE}"""


CRITIC_SYSTEM_PROMPT = (
    """\
You check a cold email before it goes to a person. Answer two questions.

grounded: is every fact about the recipient's company, every date and every number in the
email supported by the research notes, and every claim about the sender supported by what is
said about the sender and the sender facts? If the research notes list a recent dated news
item or market development, does the email open with one of them and state it correctly?

human: does it read as typed by a person to a peer? It does not if it has stock phrases (a
"hope you are well" opening, "reaching out", "synergies", "strong potential"), flattery,
marketing adjectives, a list in disguise, or the same cadence in every paragraph.

Return one JSON object and nothing else:
{"grounded": true or false, "human": true or false,
 "problem": "<what to change, naming the exact phrases; empty if both are fine>"}
"""
    + UNTRUSTED_RULE
)


def _list(items: Sequence[str]) -> str:
    return "\n".join(f"- {item}" for item in items if item) or "(none)"


def _dated(items: Sequence[Mapping[str, Any]]) -> str:
    lines = []
    for item in items:
        when = f"[{item['date']}] " if item.get("date") else ""
        detail = f" {item['detail']}" if item.get("detail") else ""
        matters = f" Why it matters to them: {item['matters']}" if item.get("matters") else ""
        lines.append(
            f"- {when}{item.get('headline', '')}.{detail}{matters} (url: {item.get('url', '')})"
        )
    return "\n".join(lines) or "(none)"


def research_notes(research: Mapping[str, Any]) -> str:
    """The web-derived notes shared by the writer and the checker (fenced as untrusted)."""
    return untrusted_text(
        f"Summary: {research.get('summary', '')}\n"
        f"Recent news about the company:\n{_dated(research.get('news_items') or [])}\n"
        f"Market developments that may matter to them:\n{_dated(research.get('triggers') or [])}\n"
        f"Products:\n{_list(research.get('products', []))}\n"
        f"From their own site (not news):\n{_list(research.get('news', []))}\n"
        f"Hook ideas from their site:\n{_list(research.get('hooks', []))}\n"
        f"Hiring: {research.get('hiring', '')}"
    )


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
    previous: str = "",
) -> str:
    parts = [
        f"## Sender: {sender.get('company_name', '')}\n{sender.get('narrative', '')}".strip(),
        "## What the sender wants from these emails\n"
        + (str(sender.get("outreach_goal") or "").strip() or "a short conversation"),
        "## Sender facts you may use\n"
        + _list(
            [
                *map(str, sender.get("value_propositions", [])),
                *map(str, sender.get("case_studies", [])),
            ]
        ),
        f"## Recipient\n{recipient}, {title or 'role unknown'}, at {company}",
        "## Research notes (from the web)\n" + research_notes(research),
        "## Answers to research questions (from the web)\n"
        + untrusted_text(_list([f"{q}: {a}" for q, a in answers.items() if a])),
        f"## Operator notes about this lead\n{notes or '(none)'}",
    ]
    styles = [str(s).strip() for s in sender.get("style_examples") or [] if str(s).strip()]
    if styles:
        shown = "\n\n---\n\n".join(styles[:4])
        parts.append(f"## {STYLE_EXAMPLES_NOTE}\n{shown}")
    if examples:
        shown = "\n\n".join(
            f"Engine wrote:\n{generated}\n\nOperator sent:\n{final}"
            for generated, final in examples
        )
        parts.append(f"## Earlier drafts the operator corrected\n{shown}")
    if feedback:
        last = f"Your last draft:\n{previous}\n\n" if previous else ""
        parts.append(
            f"## Fix these problems from your last attempt\n{last}Problems:\n{feedback}\n"
            "Rewrite it so these are fixed. Keep what was good."
        )
    return "\n\n".join(parts)


def build_critic_user_prompt(
    company: str, sender: Mapping[str, Any], research: Mapping[str, Any], body: str
) -> str:
    facts = _list(
        [*map(str, sender.get("value_propositions", [])), *map(str, sender.get("case_studies", []))]
    )
    # Who the sender is counts as supported too: the writer is told the same, so "I'm at
    # Quantra" or what the narrative says they do must not be flagged as invented.
    about = f"{sender.get('company_name', '')}\n{sender.get('narrative', '')}".strip()
    return (
        f"## Company\n{company}\n\n## Research notes (from the web)\n{research_notes(research)}"
        f"\n\n## The sender\n{about or '(not given)'}"
        f"\n\n## Sender facts\n{facts}\n\n## The email to check\n{body}"
    )


REVISE_SYSTEM_PROMPT = (
    """\
You revise a cold email exactly as its sender asks. The sender's instructions come first: they
may change the tone, the length, the structure, the ask, or add information. Anything the sender
states in the instructions is true and may be used. Keep every other fact as it is in the email
or the research notes; never invent a number, customer, event or claim.

Unless the instructions say otherwise: keep the greeting line and the signature as they are,
keep it plain text, write like a person (no bullet lists, no stock phrases such as "I hope this
finds you well" or "reaching out", no hype words). Do not add a footer, links or email addresses.

Return one JSON object and nothing else:
{"body": "<the whole revised email, from the greeting to the signature, paragraphs separated by
a blank line>"}
"""
    + UNTRUSTED_RULE
)


def build_revise_user_prompt(
    *, email: str, instructions: str, research: Mapping[str, Any], sender: Mapping[str, Any]
) -> str:
    facts = _list(
        [*map(str, sender.get("value_propositions", [])), *map(str, sender.get("case_studies", []))]
    )
    about = f"{sender.get('company_name', '')}\n{sender.get('narrative', '')}".strip()
    return (
        f"## The sender's instructions\n{instructions.strip()}\n\n"
        f"## The email as it is now\n{email.strip()}\n\n"
        f"## The sender\n{about or '(not given)'}\n\n## Sender facts\n{facts}\n\n"
        f"## Research notes (from the web)\n{research_notes(research)}"
    )
