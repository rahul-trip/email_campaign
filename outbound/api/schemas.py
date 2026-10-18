"""What goes over the wire. Plain models, kept apart from the domain so either can change."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from outbound.domain.enums import (
    CompanyStatus,
    ConsentBasis,
    HoldReason,
    PolicyRule,
    Provenance,
    SuppressionKind,
    SuppressionReason,
)
from outbound.services.journey import StageState
from outbound.services.runs import RunMode


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class In(BaseModel):
    # Nothing legitimate is longer than this; it keeps one request from being enormous.
    model_config = ConfigDict(extra="forbid", str_max_length=10_000)


# ------------------------------------------------------------------ auth


class LoginIn(In):
    password: str


class Me(Out):
    user: str = "operator"


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
    country_code: str | None
    legal_entity_type: str
    priority: int
    fit_score: int | None
    fit_reason: str | None
    campaign_id: str | None
    research: dict[str, Any] | None
    research_answers: dict[str, Any] | None
    policy_decision: dict[str, Any] | None
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


class ContactOut(Out):
    id: str
    rank: int
    full_name: str | None
    title: str | None
    seniority: str | None
    linkedin_url: str | None
    source: str
    status: str
    emails: list[EmailOut]


class MessageOut(Out):
    id: str
    step: int
    state: str
    subject: str
    generated_body: str
    final_body: str | None
    edit_distance: float | None
    lint_report: dict[str, Any] | None
    snippets: dict[str, Any] | None
    sent_at: datetime | None
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


class PersonIn(In):
    full_name: str = Field(min_length=1, max_length=200)
    title: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    # Both, or neither: consent without evidence is not recorded.
    consent_basis: ConsentBasis | None = None
    consent_evidence: str | None = Field(default=None, max_length=2000)


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


class ReviewItemOut(Out):
    message: MessageOut
    company: CompanyOut
    contact: ContactOut
    flagged: bool


class ReviewDetailOut(Out):
    item: ReviewItemOut
    notes: list[str]


class ApproveIn(In):
    edited_body: str | None = None
    row_version: int | None = None


class RejectIn(In):
    reason: str


class WorkspaceSettingsIn(In):
    """Only the settings an operator may change, each with its real type."""

    safe_to_send_only: bool | None = None
    # null means "no ceiling"; 0 means "no paid calls at all". The screen sends null when blank.
    budget_per_prospect_micro_usd: int | None = Field(default=None, ge=0, le=100_000_000)
    few_shot_examples: int | None = Field(default=None, ge=0, le=20)
    timezone: str | None = Field(default=None, max_length=64)


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
    reviewed_at: str | None = None


# ------------------------------------------------------------------ privacy


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


class MailboxIn(In):
    address: str
    credentials_ref: str
    daily_cap: int = Field(default=10, ge=1, le=500)


class MailboxOut(Out):
    id: str
    address: str
    gateway: str
    sending_domain: str
    daily_cap: int
    status: str
    dns_check: dict[str, Any] | None
