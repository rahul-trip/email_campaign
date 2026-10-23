"""The 17 tables of schema v1, exactly as specified in docs/SCHEMA.md.

Rows are called ``*Row`` to keep them apart from the domain entities. Repositories turn rows
into entities; nothing outside ``outbound.db`` should import this module.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.elements import conv

from outbound.db.base import AppendOnly, Base, Identified, Mutable
from outbound.db.types import Json, UtcDateTime, enum_type, utcnow
from outbound.domain.enums import (
    AuthTokenPurpose,
    CallOutcome,
    CampaignStatus,
    CompanySource,
    CompanyStatus,
    ConsentBasis,
    ContactSource,
    ContactStatus,
    EmailStatus,
    EntityType,
    HoldReason,
    ImportAnchor,
    ImportRowStatus,
    ImportSource,
    InboundCategory,
    LegalEntityType,
    MailboxGateway,
    MailboxStatus,
    MembershipRole,
    MessageState,
    NoteSource,
    PlatformRole,
    PolicyRule,
    PolicyStage,
    Provenance,
    RunKind,
    RunStatus,
    SuppressionKind,
    SuppressionReason,
    UserStatus,
    WorkspaceStatus,
)

_NOT_NULL = "{col} IS NOT NULL"


_LIVE_MESSAGE = "state NOT IN ('cancelled', 'rejected')"


def _partial(column: str) -> Any:
    return text(_NOT_NULL.format(col=column))


def _tenant_fk(table: str, column: str, parent: str, *, ondelete: str | None = None) -> Any:
    """A foreign key that also matches the workspace (``(workspace_id, column)`` to the parent's
    ``(workspace_id, id)``), so the database refuses a link from one workspace into another.
    Foreign-key checks ignore row-level security, so this is the only thing that stops it.
    Named as the single-column key it replaced (migration 0007)."""
    return ForeignKeyConstraint(
        ["workspace_id", column],
        [f"{parent}.workspace_id", f"{parent}.id"],
        name=conv(f"fk_{table}_{column}_{parent}"),
        ondelete=ondelete,
    )


# ----------------------------------------------------------------------- tenancy and configuration


class WorkspaceRow(Identified, Base):
    __tablename__ = "workspaces"
    # Reached by slug (``/w/<slug>``); two customers may share a name (migration 0008).
    __table_args__ = (UniqueConstraint("slug"),)

    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(48))
    status: Mapped[WorkspaceStatus] = mapped_column(
        enum_type(WorkspaceStatus, "workspace_status"), default=WorkspaceStatus.ACTIVE
    )
    deletion_due_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    sender_profile: Mapped[dict[str, Any]] = mapped_column(Json)
    settings: Mapped[dict[str, Any]] = mapped_column(Json)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)


class CampaignRow(Mutable, Base):
    __tablename__ = "campaigns"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),  # target of tenant-bound foreign keys
        UniqueConstraint("workspace_id", "name"),
        CheckConstraint("min_fit_score BETWEEN 0 AND 100", name="min_fit_score_range"),
    )

    name: Mapped[str] = mapped_column(String(200))
    target_titles: Mapped[list[str]] = mapped_column(Json)
    icp_description: Mapped[str | None] = mapped_column(Text)
    min_fit_score: Mapped[int] = mapped_column(Integer, default=60)
    research_questions: Mapped[list[str]] = mapped_column(Json, default=list)
    cadence_days: Mapped[list[int]] = mapped_column(Json, default=lambda: [0, 3, 8])
    status: Mapped[CampaignStatus] = mapped_column(
        enum_type(CampaignStatus, "campaign_status"), default=CampaignStatus.ACTIVE
    )


class MailboxRow(Mutable, Base):
    __tablename__ = "mailboxes"
    __table_args__ = (
        UniqueConstraint("workspace_id", "address"),
        UniqueConstraint("workspace_id", "id"),  # target of tenant-bound foreign keys
    )

    address: Mapped[str] = mapped_column(String(320))
    gateway: Mapped[MailboxGateway] = mapped_column(enum_type(MailboxGateway, "mailbox_gateway"))
    credentials_ref: Mapped[str] = mapped_column(String(200))  # a secret's name, never the secret
    sending_domain: Mapped[str] = mapped_column(String(255))
    dns_check: Mapped[dict[str, Any] | None] = mapped_column(Json)
    warmup_started_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    daily_cap: Mapped[int] = mapped_column(Integer, default=10)
    status: Mapped[MailboxStatus] = mapped_column(
        enum_type(MailboxStatus, "mailbox_status"), default=MailboxStatus.ACTIVE
    )


class CountryPolicyRow(Mutable, Base):
    __tablename__ = "country_policies"
    __table_args__ = (
        UniqueConstraint("workspace_id", "country_code"),
        CheckConstraint("length(country_code) = 2", name="country_code_length"),
    )

    country_code: Mapped[str] = mapped_column(String(2))
    rule: Mapped[PolicyRule] = mapped_column(enum_type(PolicyRule, "policy_rule"))
    requires_corporate_subscriber: Mapped[bool] = mapped_column(Boolean, default=False)
    allowed_provenance: Mapped[list[str] | None] = mapped_column(Json)
    footer_template: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    reviewed_by: Mapped[str | None] = mapped_column(String(200))
    reviewed_at: Mapped[datetime | None] = mapped_column(UtcDateTime)


class SuppressionRow(Mutable, Base):
    __tablename__ = "suppressions"
    __table_args__ = (UniqueConstraint("workspace_id", "kind", "value_hash"),)

    kind: Mapped[SuppressionKind] = mapped_column(enum_type(SuppressionKind, "suppression_kind"))
    value_hash: Mapped[str] = mapped_column(String(64))
    reason: Mapped[SuppressionReason] = mapped_column(
        enum_type(SuppressionReason, "suppression_reason")
    )


# ----------------------------------------------------------------------- intake


class ImportBatchRow(Mutable, Base):
    __tablename__ = "import_batches"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),  # target of tenant-bound foreign keys
        _tenant_fk("import_batches", "campaign_id", "campaigns"),
        # A webhook delivery is identified by the sender's event id, kept in ``filename``. The
        # index makes "have we seen this event?" safe even when two deliveries arrive together.
        Index(
            "ux_import_batches_webhook",
            "workspace_id",
            "source",
            "filename",
            unique=True,
            sqlite_where=text("source = 'webhook'"),
            postgresql_where=text("source = 'webhook'"),
        ),
    )

    campaign_id: Mapped[str | None] = mapped_column(String(36))
    source: Mapped[ImportSource] = mapped_column(enum_type(ImportSource, "import_source"))
    filename: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[str] = mapped_column(String(200))
    counts: Mapped[dict[str, Any] | None] = mapped_column(Json)


class ImportRowRow(Mutable, Base):
    __tablename__ = "import_rows"
    __table_args__ = (
        _tenant_fk("import_rows", "batch_id", "import_batches", ondelete="CASCADE"),
        _tenant_fk("import_rows", "company_id", "companies"),
        CheckConstraint(
            "resolution_confidence BETWEEN 0 AND 1", name="resolution_confidence_range"
        ),
        Index("ix_import_rows_status", "workspace_id", "status"),
    )

    batch_id: Mapped[str] = mapped_column(String(36))
    row_number: Mapped[int | None] = mapped_column(Integer)
    raw: Mapped[dict[str, Any]] = mapped_column(Json)
    anchor: Mapped[ImportAnchor] = mapped_column(enum_type(ImportAnchor, "import_anchor"))
    resolved_domain: Mapped[str | None] = mapped_column(String(255))
    resolution_confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[ImportRowStatus] = mapped_column(enum_type(ImportRowStatus, "import_row_status"))
    reason: Mapped[str | None] = mapped_column(Text)
    company_id: Mapped[str | None] = mapped_column(String(36))


# ----------------------------------------------------------------------- accounts and people


class CompanyRow(Mutable, Base):
    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),  # target of tenant-bound foreign keys
        _tenant_fk("companies", "campaign_id", "campaigns"),
        UniqueConstraint("workspace_id", "domain"),
        CheckConstraint("country_code IS NULL OR length(country_code) = 2", name="country_length"),
        CheckConstraint("fit_score IS NULL OR fit_score BETWEEN 0 AND 100", name="fit_score_range"),
        Index("ix_companies_queue", "workspace_id", "status", "next_action_at"),
    )

    campaign_id: Mapped[str | None] = mapped_column(String(36))
    domain: Mapped[str] = mapped_column(String(255))
    name: Mapped[str | None] = mapped_column(String(300))
    country_code: Mapped[str | None] = mapped_column(String(2))
    legal_entity_type: Mapped[LegalEntityType] = mapped_column(
        enum_type(LegalEntityType, "legal_entity_type"), default=LegalEntityType.UNKNOWN
    )
    source: Mapped[CompanySource] = mapped_column(enum_type(CompanySource, "company_source"))
    priority: Mapped[int] = mapped_column(Integer, default=5)
    status: Mapped[CompanyStatus] = mapped_column(enum_type(CompanyStatus, "company_status"))
    hold_reason: Mapped[HoldReason | None] = mapped_column(enum_type(HoldReason, "hold_reason"))
    failed_stage: Mapped[str | None] = mapped_column(String(40))
    last_error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_action_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    fit_score: Mapped[int | None] = mapped_column(Integer)
    fit_reason: Mapped[str | None] = mapped_column(Text)
    email_pattern: Mapped[str | None] = mapped_column(String(100))
    research: Mapped[dict[str, Any] | None] = mapped_column(Json)
    research_answers: Mapped[dict[str, Any] | None] = mapped_column(Json)
    policy_decision: Mapped[dict[str, Any] | None] = mapped_column(Json)
    policy_skip_from: Mapped[PolicyStage | None] = mapped_column(
        enum_type(PolicyStage, "policy_stage")
    )
    manual_fields: Mapped[list[str]] = mapped_column(Json, default=list)
    row_version: Mapped[int] = mapped_column(Integer, default=1)

    __mapper_args__ = {"version_id_col": row_version}  # noqa: RUF012  (SQLAlchemy idiom)


class ContactRow(Mutable, Base):
    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),  # target of tenant-bound foreign keys
        _tenant_fk("contacts", "company_id", "companies", ondelete="CASCADE"),
        Index(
            "ux_contacts_linkedin",
            "workspace_id",
            "linkedin_url",
            unique=True,
            sqlite_where=_partial("linkedin_url"),
            postgresql_where=_partial("linkedin_url"),
        ),
    )

    company_id: Mapped[str] = mapped_column(String(36))
    full_name: Mapped[str | None] = mapped_column(String(300))
    first_name: Mapped[str | None] = mapped_column(String(150))
    last_name: Mapped[str | None] = mapped_column(String(150))
    title: Mapped[str | None] = mapped_column(String(300))
    seniority: Mapped[str | None] = mapped_column(String(100))
    linkedin_url: Mapped[str | None] = mapped_column(String(500))
    rank: Mapped[int] = mapped_column(Integer)
    source: Mapped[ContactSource] = mapped_column(enum_type(ContactSource, "contact_source"))
    status: Mapped[ContactStatus] = mapped_column(
        enum_type(ContactStatus, "contact_status"), default=ContactStatus.CANDIDATE
    )
    manual_fields: Mapped[list[str]] = mapped_column(Json, default=list)


class ContactEmailRow(Mutable, Base):
    __tablename__ = "contact_emails"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),  # target of tenant-bound foreign keys
        _tenant_fk("contact_emails", "contact_id", "contacts", ondelete="CASCADE"),
        UniqueConstraint("workspace_id", "email"),
        Index(
            "ux_contact_emails_primary",
            "contact_id",
            unique=True,
            sqlite_where=text("is_primary"),
            postgresql_where=text("is_primary"),
        ),
    )

    contact_id: Mapped[str] = mapped_column(String(36))
    email: Mapped[str | None] = mapped_column(String(320))
    status: Mapped[EmailStatus] = mapped_column(
        enum_type(EmailStatus, "email_status"), default=EmailStatus.UNVERIFIED
    )
    provenance: Mapped[Provenance] = mapped_column(enum_type(Provenance, "email_provenance"))
    found_by: Mapped[str | None] = mapped_column(String(100))
    verified_by: Mapped[str | None] = mapped_column(String(100))
    resolution_ref: Mapped[str | None] = mapped_column(String(300))
    verified_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_skipped: Mapped[bool] = mapped_column(Boolean, default=False)


class NoteRow(AppendOnly, Base):
    __tablename__ = "notes"
    __table_args__ = (
        _tenant_fk("notes", "company_id", "companies", ondelete="CASCADE"),
        _tenant_fk("notes", "contact_id", "contacts"),
    )

    company_id: Mapped[str] = mapped_column(String(36))
    contact_id: Mapped[str | None] = mapped_column(String(36))
    body: Mapped[str] = mapped_column(Text)
    source: Mapped[NoteSource] = mapped_column(enum_type(NoteSource, "note_source"))
    author: Mapped[str | None] = mapped_column(String(200))


class ConsentRow(Mutable, Base):
    __tablename__ = "consents"
    __table_args__ = (_tenant_fk("consents", "contact_id", "contacts", ondelete="CASCADE"),)

    contact_id: Mapped[str] = mapped_column(String(36))
    basis: Mapped[ConsentBasis] = mapped_column(enum_type(ConsentBasis, "consent_basis"))
    evidence: Mapped[str] = mapped_column(Text)
    recorded_by: Mapped[str] = mapped_column(String(200))
    withdrawn_at: Mapped[datetime | None] = mapped_column(UtcDateTime)


# ----------------------------------------------------------------------- outreach


class MessageRow(Mutable, Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),  # target of tenant-bound foreign keys
        _tenant_fk("messages", "company_id", "companies", ondelete="CASCADE"),
        _tenant_fk("messages", "contact_id", "contacts"),
        _tenant_fk("messages", "contact_email_id", "contact_emails"),
        _tenant_fk("messages", "mailbox_id", "mailboxes"),
        # One live message per touch. A cancelled or rejected one no longer counts, so a lead
        # released after a policy change can be given a fresh first email for the same person.
        Index(
            "ux_messages_live_touch",
            "company_id",
            "contact_id",
            "step",
            unique=True,
            sqlite_where=text(_LIVE_MESSAGE),
            postgresql_where=text(_LIVE_MESSAGE),
        ),
        CheckConstraint("step BETWEEN 0 AND 2", name="step_range"),
        Index(
            "ux_messages_rfc",
            "workspace_id",
            "rfc_message_id",
            unique=True,
            sqlite_where=_partial("rfc_message_id"),
            postgresql_where=_partial("rfc_message_id"),
        ),
    )

    company_id: Mapped[str] = mapped_column(String(36))
    contact_id: Mapped[str] = mapped_column(String(36))
    contact_email_id: Mapped[str] = mapped_column(String(36))
    mailbox_id: Mapped[str | None] = mapped_column(String(36))
    step: Mapped[int] = mapped_column(Integer)
    subject: Mapped[str] = mapped_column(Text)
    snippets: Mapped[dict[str, Any] | None] = mapped_column(Json)
    generated_body: Mapped[str] = mapped_column(Text)
    final_body: Mapped[str | None] = mapped_column(Text)
    edit_distance: Mapped[float | None] = mapped_column(Float)
    lint_report: Mapped[dict[str, Any] | None] = mapped_column(Json)
    state: Mapped[MessageState] = mapped_column(enum_type(MessageState, "message_state"))
    remote_draft_id: Mapped[str | None] = mapped_column(String(300))
    rfc_message_id: Mapped[str | None] = mapped_column(String(500))
    in_reply_to: Mapped[str | None] = mapped_column(String(500))
    scheduled_for: Mapped[datetime | None] = mapped_column(UtcDateTime)
    sent_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    row_version: Mapped[int] = mapped_column(Integer, default=1)

    __mapper_args__ = {"version_id_col": row_version}  # noqa: RUF012  (SQLAlchemy idiom)


class InboundMessageRow(Mutable, Base):
    __tablename__ = "inbound_messages"
    __table_args__ = (
        UniqueConstraint("workspace_id", "rfc_message_id"),
        _tenant_fk("inbound_messages", "mailbox_id", "mailboxes"),
        _tenant_fk("inbound_messages", "message_id", "messages"),
        _tenant_fk("inbound_messages", "company_id", "companies"),
        _tenant_fk("inbound_messages", "contact_id", "contacts"),
    )

    mailbox_id: Mapped[str] = mapped_column(String(36))
    message_id: Mapped[str | None] = mapped_column(String(36))
    company_id: Mapped[str | None] = mapped_column(String(36))
    contact_id: Mapped[str | None] = mapped_column(String(36))
    rfc_message_id: Mapped[str] = mapped_column(String(500))
    from_address: Mapped[str | None] = mapped_column(String(320))
    received_at: Mapped[datetime] = mapped_column(UtcDateTime)
    body_excerpt: Mapped[str | None] = mapped_column(Text)
    category: Mapped[InboundCategory] = mapped_column(
        enum_type(InboundCategory, "inbound_category")
    )
    confidence: Mapped[float | None] = mapped_column(Float)
    extracted: Mapped[dict[str, Any] | None] = mapped_column(Json)
    handled_at: Mapped[datetime | None] = mapped_column(UtcDateTime)


# ----------------------------------------------------------------------- runs, cost and audit


_RUNNING_PIPELINE = "status = 'running' AND kind = 'pipeline'"


class RunRow(Mutable, Base):
    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),  # target of tenant-bound foreign keys
        # One running pipeline per workspace (migration 0006): two at once would pay twice.
        Index(
            "ux_runs_one_running_pipeline",
            "workspace_id",
            unique=True,
            sqlite_where=text(_RUNNING_PIPELINE),
            postgresql_where=text(_RUNNING_PIPELINE),
        ),
    )

    kind: Mapped[RunKind] = mapped_column(enum_type(RunKind, "run_kind"))
    params: Mapped[dict[str, Any] | None] = mapped_column(Json)
    status: Mapped[RunStatus] = mapped_column(enum_type(RunStatus, "run_status"))
    counts: Mapped[dict[str, Any] | None] = mapped_column(Json)
    cost_micro_usd: Mapped[int] = mapped_column(BigInteger, default=0)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    heartbeat_at: Mapped[datetime | None] = mapped_column(UtcDateTime)  # touched between leads


class ProviderCallRow(AppendOnly, Base):
    """Response cache, cost ledger and waterfall audit trail in one append-only table."""

    __tablename__ = "provider_calls"
    __table_args__ = (
        _tenant_fk("provider_calls", "run_id", "runs"),
        _tenant_fk("provider_calls", "company_id", "companies"),
        _tenant_fk("provider_calls", "contact_id", "contacts"),
        Index(
            "ix_provider_calls_cache",
            "workspace_id",
            "provider",
            "operation",
            "request_hash",
            "created_at",
        ),
        Index("ix_provider_calls_spend", "workspace_id", "created_at"),
    )

    run_id: Mapped[str | None] = mapped_column(String(36))
    company_id: Mapped[str | None] = mapped_column(String(36))
    contact_id: Mapped[str | None] = mapped_column(String(36))
    provider: Mapped[str] = mapped_column(String(100))
    operation: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[CallOutcome] = mapped_column(enum_type(CallOutcome, "call_outcome"))
    response: Mapped[dict[str, Any] | None] = mapped_column(Json)
    cost_micro_usd: Mapped[int] = mapped_column(BigInteger, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer)


class EventRow(AppendOnly, Base):
    """Every status change, field change and decision, for the timeline and for audit."""

    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_entity", "workspace_id", "entity_type", "entity_id", "created_at"),
    )

    entity_type: Mapped[EntityType] = mapped_column(enum_type(EntityType, "entity_type"))
    entity_id: Mapped[str] = mapped_column(String(36))
    type: Mapped[str] = mapped_column(String(60))
    actor: Mapped[str] = mapped_column(String(200))
    data: Mapped[dict[str, Any]] = mapped_column(Json)


# ----------------------------------------------------------------------- identity (Phase 6b)
# Platform tables: no row-level security. They are reached only through the identity
# repositories (outbound.db.identity), every query with an explicit predicate.


class UserRow(Identified, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email"),)

    email: Mapped[str] = mapped_column(String(320))  # stored lower-cased
    name: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str] = mapped_column(String(300))
    platform_role: Mapped[PlatformRole | None] = mapped_column(
        enum_type(PlatformRole, "platform_role")
    )
    status: Mapped[UserStatus] = mapped_column(
        enum_type(UserStatus, "user_status"), default=UserStatus.ACTIVE
    )
    last_login_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    terms_version: Mapped[str | None] = mapped_column(String(40))
    terms_accepted_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)


class MembershipRow(Identified, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id"),)

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[MembershipRole] = mapped_column(enum_type(MembershipRole, "membership_role"))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)


class AuthTokenRow(Identified, Base):
    """A single-use link: an invitation to a workspace, or a password reset."""

    __tablename__ = "auth_tokens"
    __table_args__ = (UniqueConstraint("token_hash"),)

    purpose: Mapped[AuthTokenPurpose] = mapped_column(
        enum_type(AuthTokenPurpose, "auth_token_purpose")
    )
    email: Mapped[str] = mapped_column(String(320))
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"))
    role: Mapped[MembershipRole | None] = mapped_column(enum_type(MembershipRole, "invite_role"))
    token_hash: Mapped[str] = mapped_column(String(64))  # sha256 of the token; never the token
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    created_by: Mapped[str | None] = mapped_column(String(36))  # a user id
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class SessionRow(Identified, Base):
    """A signed-in browser. The cookie holds a random token; only its hash is stored."""

    __tablename__ = "sessions"
    __table_args__ = (UniqueConstraint("token_hash"),)

    token_hash: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)  # the absolute limit
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    data: Mapped[dict[str, Any] | None] = mapped_column(Json)  # OAuth state for 6c


class AuditRow(Identified, Base):
    """Who did what to whom, for security and the admin console. Append-only."""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_workspace", "workspace_id", "created_at"),)

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    actor_user_id: Mapped[str | None] = mapped_column(String(36))
    workspace_id: Mapped[str | None] = mapped_column(String(36))  # no key: survives deletion
    action: Mapped[str] = mapped_column(String(80))
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(Json, default=dict)
