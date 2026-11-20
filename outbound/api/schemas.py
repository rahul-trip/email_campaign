"""What goes over the wire. Plain models, kept apart from the domain so either can change."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from outbound.domain.enums import (
    CandidateVerdict,
    CompanyStatus,
    ConsentBasis,
    FailureKind,
    HoldReason,
    PolicyRule,
    PolicyStage,
    Provenance,
    SuppressionKind,
    SuppressionReason,
)
from outbound.domain.outcomes import Bucket, bucket_of, tries_allowed
from outbound.domain.qualification import is_hot
from outbound.domain.vendors import MAX_KEYS_PER_ADD
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
    # A workspace of theirs was deleted: they ask the staff for a new one instead of making one.
    needs_new_workspace: bool = False


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


class DeleteAccountIn(In):
    password: str = Field(max_length=256)


class InvitationOut(Out):
    email: str
    workspace_name: str | None  # None: an invitation to Outbound itself, not to a workspace
    role: Literal["admin", "member"] | None
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


class JoinRequestOut(Out):
    id: str
    user_id: str
    email: str
    name: str
    requested_at: datetime


class TeamOut(Out):
    members: list[MemberOut]
    invitations: list[PendingInviteOut]
    requests: list[JoinRequestOut]
    join_code: str | None


class JoinCodeOut(Out):
    join_code: str


class DecideJoinIn(In):
    role: Literal["admin", "member"] = "member"


class CreateWorkspaceIn(In):
    name: str = Field(min_length=1, max_length=200)
    website: str = Field(default="", max_length=255)


class WorkspaceRequestIn(In):
    name: str = Field(min_length=1, max_length=200)
    website: str = Field(default="", max_length=255)
    note: str = Field(default="", max_length=1000)


class MyWorkspaceRequestOut(Out):
    name: str
    created_at: datetime


class JoinIn(In):
    code: str = Field(min_length=1, max_length=40)


class MyJoinRequestOut(Out):
    id: str
    workspace_name: str
    status: Literal["pending", "approved", "rejected"]
    created_at: datetime


class NotificationOut(Out):
    id: str
    kind: Literal[
        "join_requested",
        "join_approved",
        "join_rejected",
        "drafts_ready",
        "hot_lead",
        "needs_attention",
        "auto_approved",
        "run_finished",
        "run_failed",
        "discovery_paused",
        "account",
        "platform_alert",
    ]
    workspace_id: str | None
    data: dict[str, Any]
    read: bool
    created_at: datetime


class NotificationsOut(Out):
    items: list[NotificationOut]
    unread: int


class ReadIn(In):
    id: str | None = None  # one notification; none means all of them


class PlatformInviteIn(In):
    email: str = Field(max_length=320)


class PlatformInvitationOut(Out):
    id: str
    email: str
    expires_at: datetime


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
    failure_kind: FailureKind | None = None
    attempts: int = 0
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
    # A LinkedIn message is written (or sent) for someone here, so a stopped lead still has a way
    # in. Filled by the routes that list leads and open one; false elsewhere.
    has_linkedin: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def hot(self) -> bool:
        """A fit score above 80: shown with a flame, and never approved automatically."""
        return is_hot(self.fit_score)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def max_tries(self) -> int:
        """How many tries a failed lead gets in all (shown as "try 2 of 5")."""
        return tries_allowed(self.failure_kind)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def bucket(self) -> Bucket:
        """Where the lead stands for a person: ready, working, needs a decision, screened out."""
        return bucket_of(
            self.status,
            hold_reason=self.hold_reason,
            failure_kind=self.failure_kind,
            attempts=self.attempts,
            fit_score=self.fit_score,
            waiting_for_credit=self.credit_wait_step is not None,
            has_linkedin=self.has_linkedin,
        )


class LeadSummaryOut(Out):
    contact_name: str | None
    contact_title: str | None
    email_status: str | None
    credits_milli: int  # AI credits used on the lead, in thousandths


class CompanyRowOut(CompanyOut):
    summary: LeadSummaryOut | None = None  # only with ``include=summary``


class CompanyPage(Out):
    items: list[CompanyRowOut]
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
    placement_note: str | None = None  # why they are unconfirmed or not here
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
    credits_milli: int
    latency_ms: int | None
    contact_id: str | None
    asked: str = ""
    got: str = ""


class FactOut(Out):
    label: str
    value: str


class CallOut(Out):
    at: datetime
    provider: str
    operation: str
    outcome: str
    credits_milli: int
    asked: str = ""
    got: str = ""


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
    credits_milli: int


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
    total_credits_milli: int


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
    # A LinkedIn profile address; "" removes the one held. Left out: unchanged.
    linkedin_url: str | None = Field(default=None, max_length=500)


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
    # AI credits a lead may use. null means "no ceiling"; 0 means "no paid calls at all". The
    # screen sends null when blank.
    budget_per_prospect_credits: int | None = Field(default=None, ge=0, le=1_000_000)
    few_shot_examples: int | None = Field(default=None, ge=0, le=20)
    timezone: str | None = Field(default=None, max_length=64)
    country_policy_enabled: bool | None = None
    footer_enabled: bool | None = None
    email_min_words: int | None = Field(default=None, ge=40, le=500)
    email_max_words: int | None = Field(default=None, ge=40, le=600)
    auto_discovery: bool | None = None
    auto_approve_cold: bool | None = None
    guess_verified_addresses: bool | None = None
    auto_discovery_per_day: int | None = Field(default=None, ge=1, le=6)
    auto_discovery_review_limit: int | None = Field(default=None, ge=1, le=500)


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
    skip_directory: bool = False  # needs the directory_bypass ability


class RunOut(Out):
    id: str
    kind: str
    status: str
    params: dict[str, Any] | None
    counts: dict[str, Any] | None
    credits_milli: int  # AI credits the run used, in thousandths
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class AutoDiscoveryOut(Out):
    reason: (
        Literal[
            "off",
            "no_campaign",
            "no_credits",
            "run_in_progress",
            "review_full",
            "backlog",
            "not_yet",
        ]
        | None
    )  # why nothing is queued now; None: a search is due
    campaign: str | None
    last_search: datetime | None
    next_search: datetime | None
    per_day: int
    review_limit: int
    waiting_for_review: int


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
    source: str
    angle: str
    found: int
    pages: list[str]


class CandidateOut(Out):
    id: str
    run_id: str | None
    name: str
    domain: str | None
    sources: list[str]
    source_urls: list[str]
    description: str
    evidence: str
    screen_score: int | None
    rank_score: int | None
    verdict: CandidateVerdict
    reason: str
    company_id: str | None


class PromoteIn(In):
    domain: str | None = Field(default=None, max_length=255)


class RunCallOut(Out):
    provider: str
    operation: str
    calls: int
    found: int
    nothing: int
    reused: int
    errors: int
    blocked: int
    credits_milli: int
    avg_latency_ms: int | None


class StatusOut(Out):
    by_status: dict[str, int]
    held: dict[str, int]
    waiting_for_review: int
    waiting_hot: int  # of those, the ones whose lead scores above 80
    buckets: dict[str, int]  # ready, working, decision, screened_out, done


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


class SourceYieldOut(Out):
    source: str
    found: int  # companies it named
    leads: int  # of those, how many became leads
    qualified: int  # of those, how many passed the fit gate
    rate: float  # qualified / found
    days: int  # the window counted


class VendorErrorsOut(Out):
    provider: str
    calls: int  # calls that reached the vendor
    errors: int
    error_rate: float


class FunnelOut(Out):
    days: int
    named: int  # companies discovery named
    judged: int  # of those, scored by the model
    judged_share: float | None
    lead_share: float | None  # companies that became leads, of those named
    verdicts: dict[str, int]  # what screening decided, by verdict
    leads: int  # companies added in the period
    outcomes: dict[str, int]  # where they are now: waiting, failed:<stage>, held:<reason>, status
    vendors: list[VendorErrorsOut]


class CostOut(Out):
    """AI credits used, in thousandths."""

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
    icp_brief: dict[str, Any] | None = None
    status: Literal["active", "paused", "archived"] = "active"
    brief_gaps: list[str] = []  # what the brief leaves out that weakens discovery and scoring
    title_warnings: list[str] = []  # wanted "job titles" that are not jobs


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
    icp_brief: dict[str, Any] | None = None  # cleaned by ``domain.brief.Brief``


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


class ProfileDraftIn(In):
    website: str = Field(default="", max_length=300)


class ProfileDraftOut(Out):
    drafted: bool
    reason: (
        Literal[
            "no_model", "no_search", "bad_website", "site_unreadable", "model_failed", "daily_limit"
        ]
        | None
    )
    fields: dict[str, Any]
    pages: list[str]


class CampaignDraftOut(Out):
    drafted: bool
    reason: Literal["no_model", "profile_empty", "model_failed"] | None
    target_titles: list[str]
    icp_description: str
    research_questions: list[str]


class CreditsOut(Out):
    """A workspace's AI credits this period. Whole credits, except the ``_milli`` counts."""

    monthly: int | None  # from the plan (and any override); None: unlimited
    granted: int  # from active grants
    allowance: int | None  # monthly plus granted; None: unlimited
    used_milli: int  # used this period, in thousandths
    remaining_milli: int | None  # None: unlimited


class GrantOut(Out):
    id: str
    step: str | None  # only on grants made before AI credits
    amount: int  # AI credits
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
    credits: CreditsOut
    grants: list[GrantOut]
    waiting_leads: dict[str, int]  # leads parked for AI credits, per step they wait at
    waiting_rows: int  # manual rows waiting to become leads
    seats: int | None
    mailboxes: int | None
    active_campaigns: int | None
    features: list[str]
    announcement: str


class RequestCreditsIn(In):
    amount: int | None = Field(default=None, ge=1, le=10_000_000)  # AI credits wanted
    note: str = Field(default="", max_length=500)


class ResumedOut(Out):
    leads: int
    rows: int


# ----------------------------------------------------------------------- admin console (6d)


class AdminCreditsOut(Out):
    plan_monthly: int | None  # the plan's own AI credits a month; None: unlimited
    monthly: int | None  # after this customer's overrides
    granted: int
    allowance: int | None  # monthly plus granted
    used_milli: int  # this period, in thousandths
    remaining_milli: int | None


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
    deletion_due_at: datetime | None = None  # set while it waits to be deleted
    plan_code: str
    plan_name: str
    access: Literal["full", "read_only", "locked"]
    access_until: datetime | None
    period_start: datetime
    period_end: datetime
    credits: AdminCreditsOut
    credits_milli: int  # AI credits used this calendar month, in thousandths
    cost_micro_usd: int  # what those calls cost the platform (staff only)
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
    max_prospect_budget_credits: int | None


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
    kind: Literal["credit_request", "access_ending", "mailbox", "deletion_due", "workspace_request"]
    workspace_id: str
    workspace_name: str
    detail: str
    user_id: str | None = None


class DeleteCustomerIn(In):
    confirm: str = Field(max_length=200)  # the customer's name, typed again
    now: bool = False  # skip the grace period
    note: str = Field(default="", max_length=500)


class WorkspaceRequestOut(Out):
    user_id: str
    email: str
    name: str
    website: str
    note: str
    created_at: datetime


class ApproveWorkspaceIn(In):
    name: str = Field(min_length=1, max_length=200)
    website: str = Field(default="", max_length=255)


class WorkerOut(Out):
    alive: bool  # reported within the last three minutes
    last_beat_at: datetime | None
    threads: int | None  # workspaces it can work on at once
    busy: int | None  # workspaces it was working on at its last report
    overdue_ticks: int | None  # workspaces whose 15-minute pass is more than half an interval late
    queued: int  # runs waiting for it, now
    oldest_queued_seconds: int | None  # how long the longest-waiting one has waited


class OverviewOut(Out):
    customers: int
    expiring: int
    leads_added: int
    drafts_made: int
    credits_milli: int  # AI credits used this month, all customers, in thousandths
    credits_by_provider: dict[str, int]
    cost_micro_usd: int  # what those calls cost the platform
    cost_by_provider: dict[str, int]
    waiting: int
    waiting_customers: int
    worker: WorkerOut
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
    amount: int = Field(ge=1, le=10_000_000)  # AI credits
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
    monthly_credits: int | None  # AI credits a month; None: unlimited
    seats: int | None
    mailboxes: int | None
    active_campaigns: int | None
    max_leads_per_run: int | None
    max_prospect_budget_credits: int | None
    features: list[str]
    access_days: int | None
    customers: int  # how many are on it now


class PlansOut(Out):
    plans: list[PlanDefinition]
    default_plan: str
    credit_value_micro_usd: int  # the vendor and model cost one AI credit stands for
    can_edit: bool  # superadmins define plans; other staff see them
    version: int


class PlanSaveIn(In):
    name: str = Field(min_length=1, max_length=100)
    monthly_credits: int | None = Field(default=100, ge=0, le=100_000_000)
    seats: int | None = Field(default=3, ge=0)
    mailboxes: int | None = Field(default=1, ge=0)
    active_campaigns: int | None = Field(default=2, ge=0)
    max_leads_per_run: int | None = Field(default=None, ge=0)
    max_prospect_budget_credits: int | None = Field(default=50, ge=0)
    features: list[str] = Field(default_factory=lambda: ["discovery"])
    access_days: int | None = Field(default=30, ge=1)
    version: int


class DefaultPlanIn(In):
    plan: str
    version: int


class CreditValueIn(In):
    credit_value_micro_usd: int = Field(ge=1, le=100_000_000)
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


class VendorKeyOut(Out):
    slot: int
    key: str  # masked, never the key
    version: int
    set_at: datetime
    set_by: str | None
    can_roll_back: bool


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
    credits_milli: int  # AI credits used this month, in thousandths
    cost_micro_usd: int  # what those calls cost the platform this month
    cap_credits: int | None
    key_refusals: int
    can_test: bool
    keys: list[VendorKeyOut]  # every live key in the database; each call uses one at random
    balance: float | None = None  # what the vendor says the account has left, if it can say
    balance_unit: str = ""  # "searches" or "credits"
    balance_note: str = ""  # for example "resets 2026-12-16"
    paused_for_credit: bool = False  # paused by itself: it ran out, and resumes when it has more


class LlmChargeOut(Out):
    model: str
    per_million_input: float  # AI credits
    per_million_output: float


class LlmProviderOut(Out):
    """A kind of model endpoint the engine can call, for the Add a model form."""

    code: str
    needs_key: bool
    needs_base_url: bool
    default_base_url: str


class LlmModelOut(Out):
    code: str
    label: str
    provider: str
    model: str
    base_url: str
    temperature: float
    max_tokens: int
    reasoning_effort: str
    input_credits: float  # AI credits per million input tokens
    output_credits: float
    key: str  # masked, or "" when it has none (it then uses the Language model vendor's key)


class LlmModelIn(In):
    label: str = Field(min_length=1, max_length=100)
    provider: Literal[
        "openai_compatible", "openai", "anthropic", "gemini", "ollama", "github_copilot"
    ]
    model: str = Field(min_length=1, max_length=200)
    base_url: str = Field(default="", max_length=500)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=4_000, ge=16, le=200_000)
    reasoning_effort: Literal["", "low", "medium", "high"] = ""
    input_credits: float = Field(default=0, ge=0, le=1_000_000)
    output_credits: float = Field(default=0, ge=0, le=1_000_000)
    # None keeps the stored key; "" removes it; anything else replaces it. Never echoed back.
    api_key: str | None = Field(default=None, max_length=2_000)


class ChooseModelsIn(In):
    default_model: str = Field(default="", max_length=60)  # "": the LLM_* settings
    writer_model: str = Field(default="", max_length=60)  # "": the default model writes too
    extract_model: str = Field(default="", max_length=60)  # "": the default reads sites and news


class VendorsOut(Out):
    vendors: list[VendorOut]
    llm: dict[str, str | int | float]
    llm_charges: list[LlmChargeOut]  # what each model's calls use, in AI credits
    models: list[LlmModelOut]
    default_model: str
    writer_model: str
    extract_model: str
    providers: list[LlmProviderOut]


class VendorKeyIn(In):
    key: str


class VendorKeysIn(In):
    """Keys to add to a vendor, each in a new slot (pasted one per line in the console)."""

    keys: list[str] = Field(min_length=1, max_length=MAX_KEYS_PER_ADD)


class KeysAddedOut(VendorsOut):
    added: int
    already_there: int  # live already, or given twice: not added again


class VendorPauseIn(In):
    paused: bool


class LlmChargeIn(In):
    model: str = Field(min_length=1, max_length=200)
    per_million_input: float = Field(ge=0, le=1_000_000)  # AI credits per million tokens
    per_million_output: float = Field(ge=0, le=1_000_000)


class LlmSettingsIn(In):
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_base_url: str | None = None
    llm_copy_model: str | None = None
    llm_extract_model: str | None = None
    llm_temperature: float | None = None
    llm_max_tokens: int | None = None
    # Replaces every model's charge when given; omitted: the charges stay as they are.
    charges: list[LlmChargeIn] | None = None


class RevealedKeyOut(Out):
    key: str


class VendorCapIn(In):
    cap_credits: int | None = Field(default=None, ge=0)  # AI credits a month; null: no cap


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
    saved_credits_milli: int  # AI credits the hits saved, at a finder call's price


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


class PeopleCheckOut(Out):
    checked: int
    works_here: int
    not_here: int
    unsure: int


class FindPeopleIn(In):
    """Roles to look for (blank: the campaign's job titles) and what to do with who is found."""

    roles: list[str] = Field(default_factory=list, max_length=4)
    reach: Literal["none", "email", "linkedin", "both"] = "none"


class ReachedPersonOut(Out):
    contact_id: str
    name: str
    title: str | None
    linkedin_url: str | None
    confirmed: bool  # placed at the company; the rest wait for you to confirm them
    email: str  # "asked", or why not; blank when not asked for
    linkedin: str  # "written", or why not; blank when not asked for


class PeopleFoundOut(Out):
    found: int  # profiles the search returned
    added: int  # new people at the lead (the rest were already there)
    works_here: int  # of those added, placed at the company
    unsure: int  # of those added, waiting for you to confirm
    retried: bool  # the lead had failed for want of a person and goes back to the people step
    people: list[ReachedPersonOut] = []  # who was added, and what was done for each
    queued_run_id: str | None = None  # a run is looking for the email addresses asked for


class FindPeopleManyIn(FindPeopleIn):
    company_ids: list[str] = Field(min_length=1, max_length=20)


class FoundForLeadOut(Out):
    company_id: str
    found: int
    added: int
    people: list[ReachedPersonOut]
    email_asked: int
    error: str  # the search failed for this lead


class FindPeopleManyOut(Out):
    leads: list[FoundForLeadOut]
    queued_run_id: str | None = None


class NotHereIn(In):
    note: str = ""


class RetryEmailOut(Out):
    queued_run_id: str


class FindEmailAgainIn(In):
    company_ids: list[str] = Field(min_length=1, max_length=200)


class RetryManyIn(In):
    company_ids: list[str] = Field(min_length=1, max_length=200)


class RetryManyOut(Out):
    queued_run_id: str | None  # None: nothing was retried, so no run was queued
    retried: int
    skipped: int


class FindEmailAgainOut(Out):
    queued_run_id: str | None  # None: nothing was asked for, so no run was queued
    asked: int
    skipped: int


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


class KeyCheckOut(Out):
    ok: bool | None  # None: this vendor cannot be tested from here
    message: str


# ------------------------------------------------------------------ LinkedIn messages


class LinkedInDraftOut(Out):
    id: str
    company_id: str
    contact_id: str
    note: str
    message: str
    state: str
    issues: list[str]
    edited: bool
    sent_at: datetime | None = None
    created_at: datetime | None = None


class LinkedInDraftRowOut(Out):
    """A message with who it is for, for the LinkedIn page."""

    item: LinkedInDraftOut
    company_name: str | None
    domain: str
    person: str | None
    title: str | None
    profile: str | None
    fit_score: int | None = None
    company_bucket: Bucket = Bucket.WORKING
    company_status: CompanyStatus = CompanyStatus.NEW
    failure_kind: FailureKind | None = None
    country_code: str | None = None
    fit_reason: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def hot(self) -> bool:
        return is_hot(self.fit_score)


class LinkedInDraftPage(Out):
    items: list[LinkedInDraftRowOut]
    total: int


class LinkedInEditIn(In):
    note: str
    message: str


class LinkedInSentOut(Out):
    item: LinkedInDraftOut
    email_held: bool


# --------------------------------------------------------------------------- web3 read models


class DayOut(Out):
    day: date
    leads: int
    approved: int
    reviewed: int
    sent: int
    credits_milli: int  # AI credits used that day, in thousandths


class DailyOut(Out):
    days: list[DayOut]
    review_streak: int  # consecutive days, ending today or yesterday, with a review by a person


class FitBandOut(Out):
    start: int  # 0, 10, ... 90 (90 holds 90 to 100)
    count: int


class FitOut(Out):
    campaign_id: str | None
    campaign: str | None
    min_fit_score: int | None
    bands: list[FitBandOut]
    scored: int
    unscored: int


class PlannedSourceOut(Out):
    source: str
    suited: bool
    why_not: str | None
    share: float
    found: int | None  # its 90-day record, when it has one
    qualified: int | None
    rate: float | None


class DiscoveryPlanOut(Out):
    campaign: str | None
    sources: list[PlannedSourceOut]
