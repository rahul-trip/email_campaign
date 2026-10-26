"""What goes over the wire. Plain models, kept apart from the domain so either can change."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from outbound.domain.enums import (
    CompanyStatus,
    ConsentBasis,
    HoldReason,
    PolicyRule,
    PolicyStage,
    Provenance,
    SuppressionKind,
    SuppressionReason,
)
from outbound.services.journey import StageState
from outbound.services.runs import RunMode

StepName = Literal["discovery", "manual", "research", "email", "copy", "deliver", "rewrite"]


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class In(BaseModel):
    # Nothing legitimate is longer than this; it keeps one request from being enormous.
    model_config = ConfigDict(extra="forbid", str_max_length=10_000)


# ------------------------------------------------------------------ auth


class LoginIn(In):
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)


class UserOut(Out):
    id: str
    email: str
    name: str
    platform_role: Literal["admin", "superadmin"] | None = None


class MyWorkspace(Out):
    id: str
    slug: str
    name: str
    status: str
    role: Literal["admin", "member"] | None  # None: a superadmin viewing, read-only


class Me(Out):
    user: UserOut
    workspaces: list[MyWorkspace]


class RemovalIn(In):
    email: str


class RemovalConfirmIn(In):
    token: str


class ForgotIn(In):
    email: str = Field(max_length=320)


class ResetIn(In):
    token: str = Field(max_length=200)
    password: str = Field(max_length=256)


class ChangePasswordIn(In):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


class InvitationOut(Out):
    email: str
    workspace_name: str
    role: Literal["admin", "member"]
    has_account: bool


class AcceptIn(In):
    name: str = Field(default="", max_length=200)
    password: str | None = Field(default=None, max_length=256)
    accept_terms: bool = False


class MemberOut(Out):
    user_id: str
    email: str
    name: str
    role: Literal["admin", "member"]
    last_login_at: datetime | None


class PendingInviteOut(Out):
    id: str
    email: str
    role: Literal["admin", "member"]
    expires_at: datetime


class TeamOut(Out):
    members: list[MemberOut]
    invitations: list[PendingInviteOut]


class InviteIn(In):
    email: str = Field(max_length=320)
    role: Literal["admin", "member"] = "member"


class RoleIn(In):
    role: Literal["admin", "member"]


class CustomerIn(In):
    name: str = Field(min_length=1, max_length=200)
    website: str = Field(default="", max_length=255)
    admin_email: str = Field(max_length=320)


class CustomerOut(Out):
    workspace_id: str
    slug: str
    invited: str


# ------------------------------------------------------------------ leads


class CompanyOut(Out):
    id: str
    domain: str
    name: str | None
    source: str
    status: CompanyStatus
    hold_reason: HoldReason | None
    failed_stage: str | None
    last_error: str | None
    credit_wait_step: StepName | None = None  # waiting, in place, for a credit on this step
    country_code: str | None
    legal_entity_type: str
    priority: int
    fit_score: int | None
    fit_reason: str | None
    campaign_id: str | None
    research: dict[str, Any] | None
    research_answers: dict[str, Any] | None
    policy_decision: dict[str, Any] | None
    policy_skip_from: str | None = None
    manual_fields: list[str]
    next_action_at: datetime | None
    row_version: int
    created_at: datetime | None
    updated_at: datetime | None


class CompanyPage(Out):
    items: list[CompanyOut]
    total: int


class EmailOut(Out):
    id: str
    email: str | None
    status: str
    provenance: Provenance
    is_primary: bool
    found_by: str | None
    verified_by: str | None
    verified_at: datetime | None = None
    verification_skipped: bool = False


class ContactOut(Out):
    id: str
    rank: int
    full_name: str | None
    title: str | None
    seniority: str | None
    linkedin_url: str | None
    source: str
    status: str
    created_at: datetime | None = None
    refresh_email: bool = False  # "Find email again" is waiting for the next run
    emails: list[EmailOut]


class MessageOut(Out):
    id: str
    contact_id: str
    step: int
    state: str
    subject: str
    generated_body: str
    final_body: str | None
    edit_distance: float | None
    lint_report: dict[str, Any] | None
    snippets: dict[str, Any] | None
    sent_at: datetime | None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    row_version: int


class NoteOut(Out):
    id: str
    body: str
    source: str
    author: str | None
    created_at: datetime | None


class LeadOut(Out):
    company: CompanyOut
    contacts: list[ContactOut]
    messages: list[MessageOut]
    notes: list[NoteOut]
    held_at: str | None = None  # the stage whose country check held the lead


class TimelineOut(Out):
    at: datetime
    entity_type: str
    entity_id: str
    type: str
    actor: str
    data: dict[str, Any]


class WaterfallOut(Out):
    at: datetime
    provider: str
    operation: str
    outcome: str
    cost_micro_usd: int
    latency_ms: int | None
    contact_id: str | None


class FactOut(Out):
    label: str
    value: str


class CallOut(Out):
    at: datetime
    provider: str
    operation: str
    outcome: str
    cost_micro_usd: int


class IncidentOut(Out):
    at: datetime
    text: str


class StageOut(Out):
    key: str
    label: str
    state: StageState
    reached_at: datetime | None
    summary: str
    facts: list[FactOut]
    incidents: list[IncidentOut]
    calls: list[CallOut]
    cost_micro_usd: int


class OriginOut(Out):
    how: str
    at: datetime | None
    by: str | None
    facts: list[FactOut]


class JourneyOut(Out):
    company_id: str
    headline: str
    next_step: str
    origin: OriginOut
    stages: list[StageOut]
    total_cost_micro_usd: int


class CompanyPatch(In):
    row_version: int
    name: str | None = None
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    priority: int | None = Field(default=None, ge=1, le=9)
    campaign_id: str | None = None


class ReleaseIn(In):
    resume_to: CompanyStatus | None = None


class RecipientIn(In):
    contact_id: str


class SkipCheckIn(In):
    reason: str = Field(min_length=1, max_length=1000)


class PolicySkipIn(In):
    from_stage: PolicyStage
    reason: str = Field(min_length=1, max_length=1000)


class PersonIn(In):
    full_name: str = Field(min_length=1, max_length=200)
    title: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    # Both, or neither: consent without evidence is not recorded.
    consent_basis: ConsentBasis | None = None
    consent_evidence: str | None = Field(default=None, max_length=2000)


class PersonPatch(In):
    full_name: str | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)


class ConsentIn(In):
    basis: ConsentBasis
    evidence: str


class ConsentOut(Out):
    id: str
    basis: ConsentBasis
    evidence: str


# ------------------------------------------------------------------ targets


class TargetIn(In):
    company: str | None = None
    website: str | None = None
    email: str | None = None
    person: str | None = None
    title: str | None = None
    linkedin: str | None = None
    country: str | None = None
    notes: str | None = None
    priority: int | None = Field(default=None, ge=1, le=9)
    campaign_id: str | None = None
    validate_only: bool = False


class RowOut(Out):
    row_number: int | None
    status: str
    domain: str | None
    reason: str | None
    row_id: str | None


class IntakeOut(Out):
    batch_id: str | None
    validate_only: bool
    rows: list[RowOut]


class WaitingRowOut(Out):
    id: str
    row_number: int | None
    raw: dict[str, Any]
    resolved_domain: str | None
    resolution_confidence: float | None
    reason: str | None


class ConfirmIn(In):
    domain: str


# ------------------------------------------------------------------ review


class SkipOut(Out):
    kind: str
    text: str


class ReviewItemOut(Out):
    message: MessageOut
    company: CompanyOut
    contact: ContactOut
    flagged: bool
    skips: list[SkipOut] = []


class HistoryOut(Out):
    at: datetime
    what: str  # written, edited, approved, drafted, sent, ...
    actor: str
    detail: str | None = None


class ReviewDetailOut(Out):
    item: ReviewItemOut
    notes: list[str]
    history: list[HistoryOut] = []


class ApproveIn(In):
    edited_body: str | None = None
    row_version: int | None = None
    acknowledge_skips: bool = False  # required when the email relies on skipped checks


class ReviseIn(In):
    instructions: str = Field(min_length=1, max_length=4000)
    # The text in the editor, with the operator's edits so far; blank means the engine's text.
    current_body: str | None = Field(default=None, max_length=20000)


class RevisionOut(Out):
    body: str
    lint_report: dict[str, Any]


class RejectIn(In):
    reason: str


class WorkspaceSettingsIn(In):
    """Only the settings an operator may change, each with its real type."""

    safe_to_send_only: bool | None = None
    # null means "no ceiling"; 0 means "no paid calls at all". The screen sends null when blank.
    budget_per_prospect_micro_usd: int | None = Field(default=None, ge=0, le=100_000_000)
    few_shot_examples: int | None = Field(default=None, ge=0, le=20)
    timezone: str | None = Field(default=None, max_length=64)
    country_policy_enabled: bool | None = None
    footer_enabled: bool | None = None
    email_min_words: int | None = Field(default=None, ge=40, le=500)
    email_max_words: int | None = Field(default=None, ge=40, le=600)


class SenderProfileIn(In):
    """The sender profile. ``reviewed_at`` is accepted and ignored: only the server sets it."""

    company_name: str | None = Field(default=None, max_length=200)
    domain: str | None = Field(default=None, max_length=200)
    industry: str | None = Field(default=None, max_length=200)
    mission: str | None = Field(default=None, max_length=1000)
    geographic_focus: str | None = Field(default=None, max_length=500)
    signature_name: str | None = Field(default=None, max_length=200)
    signature_title: str | None = Field(default=None, max_length=200)
    legal_name: str | None = Field(default=None, max_length=300)
    postal_address: str | None = Field(default=None, max_length=500)
    registration_details: str | None = Field(default=None, max_length=500)
    contact_info: str | None = Field(default=None, max_length=500)
    narrative: str | None = Field(default=None, max_length=8000)
    value_propositions: list[str] | None = Field(default=None, max_length=30)
    technologies: list[str] | None = Field(default=None, max_length=30)
    target_verticals: list[str] | None = Field(default=None, max_length=30)
    case_studies: list[str] | None = Field(default=None, max_length=30)
    greeting: Literal["Hi", "Hello", "Dear"] | None = None
    outreach_goal: str | None = Field(default=None, max_length=500)
    # Emails the operator has sent: reference for voice and substance, not a template.
    style_examples: list[str] | None = Field(default=None, max_length=6)
    reviewed_at: str | None = None


# ------------------------------------------------------------------ privacy


class DeleteLeadIn(In):
    confirm_domain: str = Field(min_length=1, max_length=255)
    also_suppress_domain: bool = False


class DeleteLeadOut(Out):
    domain: str
    contacts_removed: int
    messages_removed: int
    drafts_deleted: int
    drafts_left: list[str]
    domain_suppressed: bool


class ForgetIn(In):
    email: str = Field(min_length=3, max_length=320)


class PrivacyOut(Out):
    found: bool
    messages_cancelled: int
    drafts_deleted: int
    drafts_left: list[str]


# ------------------------------------------------------------------ runs and reports


class RunIn(In):
    limit: int = Field(default=50, ge=1, le=500)
    only: list[str] = Field(default_factory=list)
    mode: RunMode = RunMode.MANUAL
    discover: int = Field(default=10, ge=1, le=50)
    campaign: str = "default"


class RunOut(Out):
    id: str
    kind: str
    status: str
    params: dict[str, Any] | None
    counts: dict[str, Any] | None
    cost_micro_usd: int
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class RunStepOut(Out):
    at: datetime
    kind: str
    from_status: str | None
    to_status: str | None
    detail: str | None


class RunLeadOut(Out):
    company_id: str
    domain: str
    name: str | None
    status: str
    outcome: str
    steps: list[RunStepOut]


class DiscoverySearchOut(Out):
    query: str
    new_leads: int
    already_leads: int


class RunCallOut(Out):
    provider: str
    operation: str
    calls: int
    found: int
    nothing: int
    reused: int
    errors: int
    blocked: int
    cost_micro_usd: int
    avg_latency_ms: int | None


class StatusOut(Out):
    by_status: dict[str, int]
    held: dict[str, int]
    waiting_for_review: int


class QualityOut(Out):
    written: int
    flagged: int
    sent: int
    unedited: int
    companies: int
    holds: dict[str, int]
    unedited_share: float | None
    flag_rate: float | None
    catch_all_share: float | None


class CostOut(Out):
    total: int
    per_prospect: int | None
    prospects: int
    by_provider: dict[str, int]
    calls_by_provider: dict[str, int]
    outcomes: dict[str, int]
    paid_calls: int


# ------------------------------------------------------------------ settings


class CampaignOut(Out):
    id: str
    name: str
    target_titles: list[str]
    icp_description: str | None
    min_fit_score: int
    research_questions: list[str]
    cadence_days: list[int]


class CampaignIn(In):
    name: str
    target_titles: list[str]
    icp_description: str | None = None
    min_fit_score: int = Field(default=60, ge=0, le=100)
    research_questions: list[str] = Field(default_factory=list, max_length=3)
    cadence_days: list[int] = Field(default_factory=lambda: [0, 3, 8])


class CampaignPatch(In):
    name: str | None = None
    target_titles: list[str] | None = None
    icp_description: str | None = None
    min_fit_score: int | None = Field(default=None, ge=0, le=100)
    research_questions: list[str] | None = Field(default=None, max_length=3)
    cadence_days: list[int] | None = None


class PolicyOut(Out):
    country_code: str
    rule: PolicyRule
    requires_corporate_subscriber: bool
    allowed_provenance: list[Provenance] | None
    footer_template: str | None
    version: int
    reviewed_by: str | None


class PolicyIn(In):
    rule: PolicyRule
    requires_corporate_subscriber: bool = False
    allowed_provenance: list[Provenance] | None = None
    footer_template: str | None = None
    reviewed_by: str | None = None


class SuppressionIn(In):
    kind: SuppressionKind
    value: str
    reason: SuppressionReason = SuppressionReason.MANUAL


class SuppressionOut(Out):
    kind: SuppressionKind
    reason: SuppressionReason
    fingerprint: str
    created_at: datetime


class MailboxOut(Out):
    id: str
    address: str
    gateway: Literal["imap", "gmail", "graph", "emailengine", "smartlead", "instantly"]
    sending_domain: str
    daily_cap: int
    status: Literal["active", "paused", "error", "needs_reconnect"]
    dns_check: dict[str, Any] | None
    owner_user_id: str | None = None
    is_default: bool = False
    sender: dict[str, Any] | None = None
    connection: dict[str, Any] | None = None  # host, port, user name, folders; never a secret
    last_checked_at: datetime | None = None


class MailboxOptionsOut(Out):
    gateways: list[Literal["imap", "gmail", "graph"]]  # what this server can connect


class OAuthStartIn(In):
    gateway: Literal["gmail", "graph"]
    login_hint: str | None = Field(default=None, max_length=320)


class OAuthStartOut(Out):
    url: str


class OAuthFinishIn(In):
    code: str = Field(max_length=4000)
    state: str = Field(max_length=200)


class OAuthFinishOut(Out):
    slug: str  # the workspace the mailbox was connected to, where the page goes back to
    mailbox: MailboxOut


class ImapIn(In):
    address: str = Field(max_length=320)
    host: str = Field(max_length=255)
    port: Literal[993, 143] = 993
    username: str | None = Field(default=None, max_length=320)
    password: str = Field(min_length=1, max_length=500)
    drafts_folder: str | None = Field(default=None, max_length=200)
    sent_folder: str | None = Field(default=None, max_length=200)


class SenderIn(In):
    signature_name: str = Field(default="", max_length=200)
    signature_title: str = Field(default="", max_length=200)
    greeting: Literal["", "Hi", "Hello", "Dear"] = ""
    style_examples: list[str] = Field(default_factory=list, max_length=4)


class MailboxCheckOut(Out):
    ok: bool
    status: str
    detail: str


class WebhookInfoOut(Out):
    path: str  # where other systems POST, on this server
    configured: bool  # whether a signing secret exists


class WebhookSecretOut(Out):
    path: str
    secret: str  # shown once


class SetupItemOut(Out):
    key: str
    title: str
    status: Literal["ok", "warning", "missing"]
    detail: str
    where: str  # settings:profile | settings:mailboxes | campaigns | compliance | targets


class SetupOut(Out):
    items: list[SetupItemOut]
    done: bool  # nothing is missing: the engine can draft
    next: SetupItemOut | None


class StepUsageOut(Out):
    step: str
    limit: int | None  # None: unlimited
    granted: int
    used: int
    remaining: int | None  # None: unlimited


class GrantOut(Out):
    id: str
    step: str
    amount: int
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    note: str


class UsageOut(Out):
    plan_code: str
    plan_name: str
    period_start: datetime
    period_end: datetime  # when the allowances renew
    access: Literal["full", "read_only", "locked"]
    access_until: datetime | None
    engine: bool  # the worker may work for this workspace
    steps: list[StepUsageOut]
    grants: list[GrantOut]
    waiting_leads: dict[str, int]  # leads parked for a credit, per step
    waiting_rows: int  # manual rows waiting to become leads
    seats: int | None
    mailboxes: int | None
    active_campaigns: int | None
    features: list[str]
    announcement: str


class RequestCreditsIn(In):
    step: (
        Literal["discovery", "manual", "research", "email", "copy", "deliver", "rewrite"] | None
    ) = None
    note: str = Field(default="", max_length=500)


class ResumedOut(Out):
    leads: int
    rows: int


# ----------------------------------------------------------------------- admin console (6d)


class AdminStepOut(Out):
    step: str
    plan_limit: int | None  # the plan's own limit; None: unlimited
    limit: int | None  # after this customer's overrides
    granted: int
    used: int
    remaining: int | None


class OverrideOut(Out):
    id: str
    key: str
    value: int | bool | None
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    note: str


class CustomerRowOut(Out):
    id: str
    name: str
    slug: str
    status: str
    plan_code: str
    plan_name: str
    access: Literal["full", "read_only", "locked"]
    access_until: datetime | None
    period_start: datetime
    period_end: datetime
    steps: list[AdminStepOut]
    spend_micro_usd: int  # this calendar month
    leads: int
    members: int
    mailboxes: int
    mailbox_problems: int
    waiting: int
    last_active: datetime | None
    open_request: bool
    near_limit: bool
    features: list[str]
    seats: int | None  # after this customer's overrides; None: unlimited
    mailbox_limit: int | None
    active_campaigns: int | None
    max_leads_per_run: int | None
    max_prospect_budget_micro_usd: int | None


class AdminMailboxOut(Out):
    id: str
    address: str
    gateway: str
    status: str
    last_checked_at: datetime | None
    dns_ok: bool | None


class AuditOut(Out):
    id: str
    at: datetime
    actor: str
    workspace: str
    workspace_id: str | None
    action: str
    target_type: str | None
    target_id: str | None
    note: str | None
    data: dict[str, Any]


class CustomerDetailOut(Out):
    row: CustomerRowOut
    overrides: list[OverrideOut]
    grants: list[GrantOut]
    members: list[MemberOut]
    mailboxes: list[AdminMailboxOut]
    requests: list[AuditOut]
    activity: list[AuditOut]
    plan_started_at: datetime | None
    plan_note: str


class AttentionOut(Out):
    kind: Literal["credit_request", "access_ending", "mailbox"]
    workspace_id: str
    workspace_name: str
    detail: str


class OverviewOut(Out):
    customers: int
    expiring: int
    leads_added: int
    drafts_made: int
    spend_micro_usd: int
    spend_by_provider: dict[str, int]
    waiting: int
    waiting_customers: int
    attention: list[AttentionOut]
    activity: list[AuditOut]


class AdminUserOut(Out):
    id: str
    email: str
    name: str
    platform_role: Literal["admin", "superadmin"] | None
    status: Literal["active", "disabled"]
    last_login_at: datetime | None
    workspaces: list[str]  # "Acme (admin)"


class PlanChangeIn(In):
    plan: str = Field(max_length=60)
    note: str = Field(default="", max_length=500)


class ExtendAccessIn(In):
    days: int | None = Field(default=None, ge=1, le=3650)
    until: datetime | None = None
    note: str = Field(default="", max_length=500)


class StatusChangeIn(In):
    status: Literal["active", "paused", "suspended"]
    note: str = Field(default="", max_length=500)


class OverrideIn(In):
    key: str = Field(max_length=80)
    value: int | bool | None  # null: unlimited
    expires_at: datetime | None = None
    note: str = Field(default="", max_length=500)


class GrantIn(In):
    step: StepName
    amount: int = Field(ge=1, le=1_000_000)
    expires_at: datetime | None = None
    note: str = Field(default="", max_length=500)
    resume_now: bool = True


class GrantedOut(Out):
    grant: GrantOut
    resumed_leads: int
    resumed_rows: int


class PlanDefinition(Out):
    code: str
    name: str
    limits: dict[str, int | None]
    seats: int | None
    mailboxes: int | None
    active_campaigns: int | None
    max_leads_per_run: int | None
    max_prospect_budget_micro_usd: int | None
    features: list[str]
    access_days: int | None
    customers: int  # how many are on it now


class PlansOut(Out):
    plans: list[PlanDefinition]
    default_plan: str
    version: int


class PlanSaveIn(In):
    name: str = Field(min_length=1, max_length=100)
    limits: dict[StepName, int | None] = Field(default_factory=dict)
    seats: int | None = Field(default=3, ge=0)
    mailboxes: int | None = Field(default=1, ge=0)
    active_campaigns: int | None = Field(default=2, ge=0)
    max_leads_per_run: int | None = Field(default=None, ge=0)
    max_prospect_budget_micro_usd: int | None = Field(default=500_000, ge=0)
    features: list[str] = Field(default_factory=lambda: ["discovery"])
    access_days: int | None = Field(default=30, ge=1)
    version: int


class DefaultPlanIn(In):
    plan: str
    version: int


class PlatformSettingsOut(Out):
    kill_runs: bool
    kill_drafts: bool
    superadmin_enabled: bool
    announcement: str
    version: int


class PlatformSettingsIn(In):
    version: int
    kill_runs: bool | None = None
    kill_drafts: bool | None = None
    superadmin_enabled: bool | None = None
    announcement: str | None = Field(default=None, max_length=1000)


class PlatformRoleIn(In):
    role: Literal["admin", "superadmin"] | None


class VendorOut(Out):
    code: str
    name: str
    role: str
    key: str  # masked, never the key
    source: str  # database, environment or none
    version: int
    set_at: datetime | None
    set_by: str | None
    paused: bool
    can_roll_back: bool
    spend_micro_usd: int
    cap_micro_usd: int | None


class VendorsOut(Out):
    vendors: list[VendorOut]
    llm: dict[str, str | int | float]


class VendorKeyIn(In):
    key: str


class VendorPauseIn(In):
    paused: bool


class LlmSettingsIn(In):
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_base_url: str | None = None
    llm_copy_model: str | None = None
    llm_temperature: float | None = None
    llm_max_tokens: int | None = None


class RevealedKeyOut(Out):
    key: str


class VendorCapIn(In):
    cap_micro_usd: int | None


class DirectoryBadgeOut(Out):
    in_directory: bool
    verified_month: str | None  # YYYY-MM; never a day
    can_skip: bool
    skipping: bool


class DirectoryReportIn(In):
    field: str
    reason: str = ""


class DirectorySkipIn(In):
    skip: bool


class DirectoryFlagOut(Out):
    id: str
    target_type: str
    target_key: str
    field: str
    reason: str
    created_at: datetime


class DirectoryFiguresOut(Out):
    companies: int
    people: int
    emails: int
    open_reports: int
    unfolded: int
    lookups: int
    hits: int
    saved_micro_usd: int


class DirectoryOverviewOut(Out):
    figures: DirectoryFiguresOut
    flags: list[DirectoryFlagOut]


class DirectoryResolveIn(In):
    accept: bool
    note: str = ""


class DirectoryHistoryOut(Out):
    at: datetime
    target: str
    source: str


class AdminRoleIn(In):
    role: Literal["admin", "member"]


class LinkedInOut(Out):
    url: str | None  # None: nothing clearly fit, so nothing was saved


class RetryEmailOut(Out):
    queued_run_id: str


class DirectoryEntryOut(Out):
    id: str
    email: str
    status: str
    provenance: str
    source: str
    verified_at: datetime
    person_id: str
    full_name: str
    first_name: str
    last_name: str
    title: str | None
    linkedin_url: str | None
    company_domain: str
    employment_status: str


class DirectoryEntriesOut(Out):
    entries: list[DirectoryEntryOut]
    total: int


class DirectoryEntryIn(In):
    email: str = Field(max_length=320)
    first_name: str = Field(max_length=150)
    last_name: str = Field(max_length=150)
    company_domain: str = Field(max_length=253)
    title: str | None = Field(default=None, max_length=300)
    linkedin_url: str | None = Field(default=None, max_length=500)


class DirectoryEntryPatch(In):
    email: str | None = Field(default=None, max_length=320)
    first_name: str | None = Field(default=None, max_length=150)
    last_name: str | None = Field(default=None, max_length=150)
    title: str | None = Field(default=None, max_length=300)
    linkedin_url: str | None = Field(default=None, max_length=500)
    status: Literal["verified", "disputed", "invalid"] | None = None
    employment_status: Literal["current", "left", "unknown"] | None = None


class DirectoryCompanyOut(Out):
    id: str
    domain: str
    name: str | None
    country_code: str | None
    email_pattern: str | None
    pattern_confidence: int
    status: str


class DirectoryCompaniesOut(Out):
    companies: list[DirectoryCompanyOut]
    total: int


class DirectoryCompanyIn(In):
    name: str | None = Field(default=None, max_length=300)
    country_code: str | None = Field(default=None, max_length=2)
    email_pattern: str | None = Field(default=None, max_length=100)
