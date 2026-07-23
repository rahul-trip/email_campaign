"""agent/prompts.py — Single source of truth for every LLM prompt in the agent.

Centralizing prompts here (rather than inline in each provider) means:
- Tuning agent behavior (tone, banned phrases, structure rules) is a one-file
  change, not a hunt through provider adapters.
- Prompt content is reviewable/diffable independent of request-plumbing code
  (retries, headers, JSON parsing) in the provider that calls it.
- When a second LLM-backed node is added (e.g. an LLM-based discovery
  filter), its prompt(s) land here too, under their own named section, so
  this file stays the one place to look for "what is the agent told to do."

Naming convention: `<ROLE>_SYSTEM_PROMPT` for the fixed system message, and
`build_<role>_user_prompt(...)` for the per-call user message. Providers
own HOW a prompt is sent (HTTP, retries, parsing); this file owns WHAT is
said.
"""

from __future__ import annotations

from agent.config.models import SenderProfile
from agent.domain.models import Company, Contact

# =============================================================================
# Copywriter agent (agent/providers/copywriter/llm_copywriter.py)
# =============================================================================
# Honors system_specification.md Module C's negative-constraint prompt
# directives — the banned-phrase list and structure rules below implement
# that spec section directly. Keep both in sync if the spec changes.

COPYWRITER_SYSTEM_PROMPT = """\
You are a world-class executive salesperson writing brief, human-sounding
outbound emails.

BANNED PHRASES (never write any of these): "I hope this email finds you well",
"I hope this finds you well", "In today's fast-paced", "revolutionary",
"delighted to connect", "synergy", "leverage", "cutting-edge", "game-changer",
"I wanted to reach out", "touch base".

STRUCTURE RULES:
- pitch_email: max 150 words. One singular, low-friction call to action.
- The first 2 sentences must hook on the contact's specific background.
- Sentences 3-5 tie the sender's real capabilities to the target's actual work.
- Sign off exactly with:
{signature_name}
{signature_title}
- follow_up: shorter than the pitch; references the prior email.
- commonalities: exactly 3 bullets of GENUINE intersections between the
  sender's real capabilities and the target's real work. Never generic filler.

Respond ONLY with a JSON object, no commentary, no markdown fences:
{{"pitch_email": "...", "follow_up": "...", "commonalities": ["...", "...", "..."]}}
"""


def build_copywriter_system_prompt(signature_name: str, signature_title: str) -> str:
    """Fill the copywriter's fixed system prompt with this run's signature."""
    return COPYWRITER_SYSTEM_PROMPT.format(
        signature_name=signature_name,
        signature_title=signature_title,
    )


def build_copywriter_user_prompt(company: Company, contact: Contact, sender: SenderProfile) -> str:
    """Build the per-lead user message: sender context + target context."""
    value_props = "\n".join(f"- {v}" for v in sender.value_propositions) or "(none listed)"
    technologies = "\n".join(f"- {t}" for t in sender.technologies) or "(none listed)"

    return f"""\
SENDER PROFILE ({sender.company_name}):
{sender.narrative or '(no narrative provided)'}

Key capabilities (for finding commonalities):
{value_props}

Technologies:
{technologies}

---

TARGET COMPANY:
Name: {company.name}
Description: {company.description or '(none available)'}

TARGET CONTACT:
Name: {contact.full_name}, {contact.title}
Background/Interests: {contact.eccentricities or '(none available)'}
"""
