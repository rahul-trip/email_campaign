"""Reading incoming mail: is it a bounce, an opt-out, an auto-reply, or something else?

Rules only (Phase 4a): the two categories the law and the sender's reputation need acted on
straight away. They are decided from the text, with no model, so the same message always gets
the same answer. Everything else is ``other`` until the later phase-4 classifier reads it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from outbound.domain.enums import InboundCategory

_BOUNCE_SENDER = re.compile(r"^(mailer-daemon|postmaster|mail delivery|no-?reply)[@ ]?", re.I)
_BOUNCE_SUBJECT = re.compile(
    r"undeliver|delivery (status notification|failure|has failed)|returned mail|mail delivery"
    r"|failure notice|could not be delivered|not delivered|address not found",
    re.I,
)
_STATUS = re.compile(r"\b([45])\.\d{1,3}\.\d{1,3}\b")
_FAILED_RECIPIENT = re.compile(
    r"(?:final|original)-recipient:\s*(?:rfc822;\s*)?<?([^\s<>;]+@[^\s<>;]+)>?"
    r"|(?:wasn't delivered to|could not be delivered to|failed:?|to the following recipient[s]?:?)"
    r"\s*<?([^\s<>;]+@[^\s<>;]+)>?",
    re.I,
)
_OUT_OF_OFFICE = re.compile(
    r"out of (the )?office|automatic reply|auto-?reply|autoreply|on (annual )?leave|away from"
    r"|abwesenheit",
    re.I,
)
_OPT_OUT = re.compile(
    r"\bunsubscribe\b|\bremove me\b|\bopt[- ]?out\b|take me off|do not (contact|email|write)"
    r"|don'?t (contact|email|write)|stop (emailing|contacting|sending|writing)"
    r"|no (further|more) (emails?|contact|messages)|remove (my|this) (email|address)",
    re.I,
)
_QUOTE = re.compile(r"^(>|on .+ wrote:|-{2,}\s*original message|from:\s)", re.I | re.M)


@dataclass(frozen=True)
class Classification:
    category: InboundCategory
    confidence: float
    failed_recipient: str | None = None  # for a bounce: who it could not reach


def _own_words(body: str) -> str:
    """What the sender wrote, without the quoted message under it."""
    found = _QUOTE.search(body)
    return body[: found.start()] if found else body


def classify(from_address: str, subject: str, body: str) -> Classification:
    sender = from_address.split("@")[0]
    if _BOUNCE_SENDER.match(sender) and (
        _BOUNCE_SUBJECT.search(subject) or _STATUS.search(body[:3000])
    ):
        status = _STATUS.search(body[:3000])
        recipient = _FAILED_RECIPIENT.search(body[:3000])
        failed = (recipient.group(1) or recipient.group(2)).lower() if recipient else None
        if status and status.group(1) == "4":
            return Classification(InboundCategory.SOFT_BOUNCE, 0.9, failed)
        return Classification(InboundCategory.HARD_BOUNCE, 0.95 if status else 0.7, failed)
    if _OUT_OF_OFFICE.search(subject) or _OUT_OF_OFFICE.search(body[:400]):
        return Classification(InboundCategory.OUT_OF_OFFICE, 0.9)
    if _OPT_OUT.search(_own_words(body)[:600]) or _OPT_OUT.search(subject):
        return Classification(InboundCategory.UNSUBSCRIBE, 0.9)
    return Classification(InboundCategory.OTHER, 0.3)
