"""Immutable snapshots of rows. Stages and policies work on these, never on ORM objects.

Field names match the database columns exactly, which is what lets a repository build one
from a row without a mapping table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from outbound.domain.enums import (
    AuthTokenPurpose,
    CallOutcome,
    CompanySource,
    CompanyStatus,
    ConsentBasis,
    ContactSource,
    ContactStatus,
    EmailStatus,
    EntityType,
    HoldReason,
    LegalEntityType,
    MembershipRole,
    MessageState,
    NoteSource,
    PlatformRole,
    PolicyRule,
    PolicyStage,
    Provenance,
    SuppressionKind,
    SuppressionReason,
    UserStatus,
    WorkspaceStatus,
)


@dataclass(frozen=True)
class CountryPolicy:
    country_code: str
    rule: PolicyRule
    version: int = 1
    requires_corporate_subscriber: bool = False
    allowed_provenance: tuple[Provenance, ...] | None = None
    footer_template: str | None = None
    reviewed_by: str | None = None

    def __post_init__(self) -> None:
        if self.allowed_provenance is not None:
            object.__setattr__(
                self, "allowed_provenance", tuple(Provenance(p) for p in self.allowed_provenance)
            )


@dataclass(frozen=True)
class Company:
    id: str
    workspace_id: str
    domain: str
    source: CompanySource
    status: CompanyStatus
    row_version: int
    campaign_id: str | None = None
    name: str | None = None
    country_code: str | None = None
    legal_entity_type: LegalEntityType = LegalEntityType.UNKNOWN
    priority: int = 5
    hold_reason: HoldReason | None = None
    failed_stage: str | None = None
    last_error: str | None = None
    attempts: int = 0
    next_action_at: datetime | None = None
    fit_score: int | None = None
    fit_reason: str | None = None
    email_pattern: str | None = None
    research: dict[str, Any] | None = None
    research_answers: dict[str, Any] | None = None
    policy_decision: dict[str, Any] | None = None
    policy_skip_from: PolicyStage | None = None  # the operator skipped the country rule from here
    manual_fields: tuple[str, ...] = field(default=())
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "manual_fields", tuple(self.manual_fields))


@dataclass(frozen=True)
class Contact:
    id: str
    workspace_id: str
    company_id: str
    rank: int
    source: ContactSource
    status: ContactStatus
    full_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    title: str | None = None
    seniority: str | None = None
    linkedin_url: str | None = None
    manual_fields: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        object.__setattr__(self, "manual_fields", tuple(self.manual_fields))


@dataclass(frozen=True)
class ContactEmail:
    id: str
    workspace_id: str
    contact_id: str
    status: EmailStatus
    provenance: Provenance
    is_primary: bool
    email: str | None = None
    found_by: str | None = None
    verified_by: str | None = None
    resolution_ref: str | None = None
    verified_at: datetime | None = None
    # The operator chose to write to this address without (or despite) a verifier's answer.
    verification_skipped: bool = False


@dataclass(frozen=True)
class Message:
    id: str
    workspace_id: str
    company_id: str
    contact_id: str
    contact_email_id: str
    step: int
    subject: str
    generated_body: str
    state: MessageState
    row_version: int
    mailbox_id: str | None = None
    snippets: dict[str, Any] | None = None
    final_body: str | None = None
    edit_distance: float | None = None
    lint_report: dict[str, Any] | None = None
    remote_draft_id: str | None = None
    rfc_message_id: str | None = None
    in_reply_to: str | None = None
    scheduled_for: datetime | None = None
    sent_at: datetime | None = None
    updated_at: datetime | None = (
        None  # when it last changed; for a drafted message, the draft time
    )


@dataclass(frozen=True)
class Note:
    id: str
    workspace_id: str
    company_id: str
    body: str
    source: NoteSource
    contact_id: str | None = None
    author: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class Consent:
    id: str
    workspace_id: str
    contact_id: str
    basis: ConsentBasis
    evidence: str
    recorded_by: str
    withdrawn_at: datetime | None = None

    @property
    def active(self) -> bool:
        return self.withdrawn_at is None


@dataclass(frozen=True)
class Workspace:
    id: str
    name: str
    slug: str
    status: WorkspaceStatus
    sender_profile: dict[str, Any]
    settings: dict[str, Any]
    deletion_due_at: datetime | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class Campaign:
    id: str
    workspace_id: str
    name: str
    target_titles: tuple[str, ...]
    min_fit_score: int
    research_questions: tuple[str, ...]
    cadence_days: tuple[int, ...]
    icp_description: str | None = None
    mailbox_id: str | None = None  # the sender; None means the workspace's default mailbox

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_titles", tuple(self.target_titles))
        object.__setattr__(self, "research_questions", tuple(self.research_questions))
        object.__setattr__(self, "cadence_days", tuple(self.cadence_days))


@dataclass(frozen=True)
class Event:
    """One line of history: a status change, a field change, a decision."""

    id: str
    entity_type: EntityType
    entity_id: str
    type: str
    actor: str
    data: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class ProviderCall:
    """One vendor call as recorded in the ledger (the response itself is not exposed)."""

    id: str
    provider: str
    operation: str
    outcome: CallOutcome
    cost_micro_usd: int
    latency_ms: int | None
    run_id: str | None
    company_id: str | None
    contact_id: str | None
    created_at: datetime


@dataclass(frozen=True)
class Suppression:
    """A do-not-contact entry. Only the hash of the value is ever held."""

    kind: SuppressionKind
    reason: SuppressionReason
    value_hash: str
    created_at: datetime


# ----------------------------------------------------------------------- identity (Phase 6b)


@dataclass(frozen=True)
class User:
    id: str
    email: str
    name: str
    platform_role: PlatformRole | None
    status: UserStatus
    last_login_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class Membership:
    id: str
    workspace_id: str
    user_id: str
    role: MembershipRole
    created_at: datetime


@dataclass(frozen=True)
class AuthToken:
    id: str
    purpose: AuthTokenPurpose
    email: str
    workspace_id: str | None
    role: MembershipRole | None
    expires_at: datetime
    used_at: datetime | None
    revoked_at: datetime | None
    created_by: str | None
    created_at: datetime


@dataclass(frozen=True)
class LoginSession:
    id: str
    user_id: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    ip: str | None
    user_agent: str | None
