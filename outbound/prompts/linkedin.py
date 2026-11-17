"""Prompts for the LinkedIn drafts: a connection note and a follow-up, written for pasting."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from outbound.domain.linkedin import MESSAGE_WORDS, NOTE_MAX_CHARS
from outbound.prompts.copy import _list, research_notes
from outbound.prompts.fence import UNTRUSTED_RULE, untrusted_text

LINKEDIN_SYSTEM_PROMPT = f"""\
You write two LinkedIn texts from one person to each of one or more named people at another
company: a separate pair for each numbered recipient. The sender pastes them into LinkedIn by
hand. Two recipients at the same company must not get the same words: open each pair from a
different fact where the notes allow it. They must read the way a thoughtful person types to a
peer: specific, plain and a little informal. Not like marketing copy and not like AI.

Return one JSON object and nothing else:
{{"drafts": [{{"n": <recipient number>, "note": "...", "message": "..."}}, ...]}}
One entry per recipient you are asked for, with that recipient's number.

note: the text sent with the connection request. At most {NOTE_MAX_CHARS} characters in all, one
or two sentences. Use one concrete thing about them or their company from the research notes
(news if there is any, else something from their site) and say why you would like to connect.
Do not pitch, do not ask for a call, no greeting line like "Dear".

message: sent after they accept. {MESSAGE_WORDS[0]} to {MESSAGE_WORDS[1]} words, two short
paragraphs at most. Say what you make of that same fact for them, say what the sender does that
bears on it (use only the sender facts), and end with one low-pressure question they can answer
in a line. Start with their first name. Do not sign off with a title or company block.

Voice
- Contractions, "I" and "we", sentences of different lengths.
- No links, email addresses, bullet points, bold, hashtags or emoji.
- No flattery ("impressive", "admire") and no hype words (leading, seamless, robust,
  cutting-edge, innovative, powerful, synergies).
- Do not say "hope this finds you well", "reaching out", "I came across", "caught my eye".
- Never invent a number, customer, event or claim. Every fact about them must be in the research
  notes; every fact about the sender must be in the sender facts.
- If the sender has already written to them by email, do not repeat that email; this is a
  separate, shorter way of saying hello.

If feedback is given for a recipient, fix exactly what it names in that pair and keep the
rest. {UNTRUSTED_RULE}"""


def build_linkedin_user_prompt(
    *,
    sender: Mapping[str, Any],
    recipients: Sequence[tuple[str, str]],
    company: str,
    research: Mapping[str, Any],
    notes: str,
    rewrites: Mapping[int, tuple[str, str, str]] | None = None,
) -> str:
    """``recipients`` are (first name, title), numbered from 1. ``rewrites`` maps a number to
    (previous note, previous message, what to fix): only those recipients are asked for."""
    parts = [
        f"## Sender: {sender.get('company_name', '')}\n{sender.get('narrative', '')}".strip(),
        f"## Signed by\n{sender.get('signature_name', '')}",
        "## What the sender wants\n"
        + (str(sender.get("outreach_goal") or "").strip() or "a short conversation"),
        "## Sender facts you may use\n"
        + _list(
            [
                *map(str, sender.get("value_propositions", [])),
                *map(str, sender.get("case_studies", [])),
            ]
        ),
        f"## Their company\n{company}",
        "## Recipients\n"
        + "\n".join(
            f"{n}. {name}, {title or 'role unknown'}"
            for n, (name, title) in enumerate(recipients, start=1)
            if not rewrites or n in rewrites
        ),
        "## Research notes (from the web)\n" + research_notes(research),
    ]
    if notes.strip():
        parts.append("## The operator's notes on this company\n" + untrusted_text(notes))
    for n, (note, message, fix) in (rewrites or {}).items():
        parts.append(
            f"## Recipient {n}: your previous draft\nnote: {note}\nmessage: {message}\n"
            f"Fix these:\n{fix}"
        )
    return "\n\n".join(parts)


def feedback_for(issues: Sequence[str]) -> str:
    return "\n".join(f"- {issue}" for issue in issues)
