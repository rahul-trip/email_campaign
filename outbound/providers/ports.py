"""Provider ports: the only interfaces the stages know about.

Each port is a small ``Protocol`` with one to three methods. Adapters in
``outbound.providers.adapters`` implement them and map vendor JSON into the models below,
so vendor payloads never reach a stage. Swapping a vendor means writing one adapter.

Results carry two audit fields for every call:

* ``raw_status``: the vendor's own label, kept for the waterfall inspector.
* ``billed``: whether the vendor charged for the call, because some vendors do not
  charge for ``unknown`` answers. The cost guard uses it to record the true cost.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --------------------------------------------------------------------------- email finding


class PersonQuery(_Model):
    """A known person whose email we want. Names are required; the rest sharpens the match."""

    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    company_name: str | None = None
    linkedin_url: str | None = None


class FinderResult(_Model):
    email: str | None  # None means the vendor looked and found nothing
    provider: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    raw_status: str = ""
    billed: bool = True


class EmailFinder(Protocol):
    name: str

    def find(self, person: PersonQuery, domain: str) -> FinderResult:
        """Look up one person's email at ``domain``. Never guesses several addresses."""
        ...


# --------------------------------------------------------------------------- verification


class VerificationStatus(StrEnum):
    VALID = "valid"
    CATCH_ALL = "catch_all"  # the server accepts every address, so the mailbox is unproven
    UNKNOWN = "unknown"
    INVALID = "invalid"


class VerificationResult(_Model):
    email: str
    status: VerificationStatus
    provider: str
    raw_status: str = ""
    billed: bool = True


class EmailVerifier(Protocol):
    name: str

    def verify(self, email: str) -> VerificationResult: ...


# --------------------------------------------------------------------------- catch-all resolution


class ResolutionStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    UNRESOLVED = "unresolved"  # the resolver finished but could not decide


class ResolutionResult(_Model):
    email: str
    status: ResolutionStatus
    provider: str
    raw_status: str = ""
    billed: bool = True


class ResolutionTicket(_Model):
    """Handle for a resolution in progress.

    Real-time resolvers answer at once and set ``result``. Asynchronous ones leave it
    ``None``; the caller stores ``ref`` and calls ``poll`` later.
    """

    ref: str
    email: str
    provider: str
    result: ResolutionResult | None = None


class CatchAllResolver(Protocol):
    name: str

    def submit(self, email: str) -> ResolutionTicket: ...

    def poll(self, ticket: ResolutionTicket) -> ResolutionResult | None:
        """Return the result, or ``None`` while the vendor is still working."""
        ...


# --------------------------------------------------------------------------- search and extract


class SearchHit(_Model):
    url: str
    title: str = ""
    snippet: str = ""
    score: float | None = None
    published_date: str | None = None  # as the vendor gives it; news searches only


class PageText(_Model):
    url: str
    text: str


class SearchProvider(Protocol):
    name: str

    def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        topic: str = "general",
        days: int | None = None,
    ) -> list[SearchHit]:
        """Web search. ``topic="news"`` searches news sources and dates each hit; ``days`` keeps
        only what was published in the last that many days."""
        ...

    def extract(self, urls: list[str]) -> list[PageText]:
        """Fetch page text. URLs the vendor could not fetch are left out, not raised."""
        ...


# --------------------------------------------------------------------------- language model


class LlmResult(_Model):
    text: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


class LlmClient(Protocol):
    name: str
    model: str

    def complete(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LlmResult:
        """One chat completion. ``json_mode`` asks for a JSON object where the vendor allows."""
        ...


# --------------------------------------------------------------------------- company registry


class RegistryEntry(_Model):
    name: str
    number: str
    status: str  # the registry's own word, for example "active" or "dissolved"
    company_type: str  # for example "ltd", "plc", "llp", "private-unlimited"
    address: str = ""


class CompanyRegistry(Protocol):
    name: str

    def search(self, company_name: str, *, max_results: int = 5) -> list[RegistryEntry]:
        """Registered companies whose name matches, best match first. Empty when none do."""
        ...


# --------------------------------------------------------------------------- mailbox


class OutgoingDraft(_Model):
    """An email for the mailbox to hold as a draft. The mailbox supplies the From address."""

    to_address: str = Field(min_length=3)
    subject: str
    body: str
    in_reply_to: str | None = None  # a follow-up threads under the previous touch
    references: str | None = None
    # A fixed Message-ID (with angle brackets) makes saving idempotent: ask ``draft_exists`` first.
    message_id: str | None = None


class SentMessage(_Model):
    rfc_message_id: str
    to_address: str
    subject: str
    sent_at: AwareDatetime
    body: str


class InboundMessage(_Model):
    rfc_message_id: str
    from_address: str
    subject: str
    received_at: AwareDatetime
    body: str
    in_reply_to: str | None = None
    references: str | None = None


class Mailbox(Protocol):
    """One operator mailbox: where drafts are saved and where sent and received mail is read."""

    address: str

    def append_draft(self, draft: OutgoingDraft) -> str:
        """Save a draft and return its ``Message-ID``, which is the handle for ``delete_draft``."""
        ...

    def draft_exists(self, remote_draft_id: str) -> bool: ...

    def delete_draft(self, remote_draft_id: str) -> int:
        """Remove drafts with this Message-ID; returns how many were removed."""
        ...

    def list_sent(self, since: datetime) -> list[SentMessage]: ...

    def list_inbox(self, since: datetime) -> list[InboundMessage]: ...
