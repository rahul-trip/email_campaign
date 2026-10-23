"""Every closed value set in the schema.

The database models use these same enums, so the ``CHECK`` constraints in the schema are
generated from them and can never drift from the code. Values are lowercase snake_case.
"""

from __future__ import annotations

from enum import StrEnum


class CompanyStatus(StrEnum):
    NEW = "new"
    RESEARCHED = "researched"
    QUALIFIED = "qualified"
    DISQUALIFIED = "disqualified"
    CONTACTS_FOUND = "contacts_found"
    EMAIL_READY = "email_ready"
    HELD = "held"
    COPY_READY = "copy_ready"
    APPROVED = "approved"
    REJECTED = "rejected"
    IN_SEQUENCE = "in_sequence"
    REPLIED = "replied"
    COMPLETED = "completed"
    SUPPRESSED = "suppressed"
    FAILED = "failed"


class HoldReason(StrEnum):
    CATCH_ALL_UNVERIFIED = "catch_all_unverified"
    CATCH_ALL_RESOLVING = "catch_all_resolving"
    CONSENT_REQUIRED = "consent_required"
    COUNTRY_UNKNOWN = "country_unknown"
    ENTITY_UNKNOWN = "entity_unknown"
    NEEDS_OPERATOR = "needs_operator"


class CompanySource(StrEnum):
    MANUAL = "manual"
    DISCOVERY = "discovery"
    IMPORT = "import"
    REFERRAL = "referral"


class LegalEntityType(StrEnum):
    CORPORATE_SUBSCRIBER = "corporate_subscriber"
    SOLE_TRADER_OR_PARTNERSHIP = "sole_trader_or_partnership"
    UNKNOWN = "unknown"


class ContactStatus(StrEnum):
    # Found by a public search whose employer could not be confirmed. Never worked on (no paid
    # lookups, no email) until the operator confirms the person works there.
    UNCONFIRMED = "unconfirmed"
    CANDIDATE = "candidate"
    ACTIVE = "active"
    BOUNCED = "bounced"
    REFERRED_AWAY = "referred_away"
    OPTED_OUT = "opted_out"
    FORGOTTEN = "forgotten"


WORKABLE_CONTACT_STATUSES = (ContactStatus.CANDIDATE, ContactStatus.ACTIVE)


class ContactSource(StrEnum):
    OPERATOR = "operator"
    SITE = "site"
    SEARCH = "search"
    DATABASE = "database"
    REFERRAL = "referral"
    OOO_ALTERNATE = "ooo_alternate"


class EmailStatus(StrEnum):
    UNVERIFIED = "unverified"
    VALID = "valid"
    CATCH_ALL_RESOLVED = "catch_all_resolved"
    CATCH_ALL_PENDING = "catch_all_pending"
    CATCH_ALL_UNVERIFIED = "catch_all_unverified"
    UNKNOWN = "unknown"
    INVALID = "invalid"


class Provenance(StrEnum):
    OPERATOR_GIVEN = "operator_given"
    PUBLICLY_PUBLISHED = "publicly_published"
    API_DATABASE = "api_database"
    PATTERN_INFERRED = "pattern_inferred"
    REFERRAL = "referral"


class ConsentBasis(StrEnum):
    EXPRESS = "express"
    CONSPICUOUS_PUBLICATION = "conspicuous_publication"
    VOLUNTARY_DISCLOSURE = "voluntary_disclosure"
    EXISTING_RELATIONSHIP = "existing_relationship"


class NoteSource(StrEnum):
    OPERATOR = "operator"
    IMPORT = "import"
    REFERRAL = "referral"
    REPLY = "reply"
    SYSTEM = "system"


class MessageState(StrEnum):
    GENERATED = "generated"
    APPROVED = "approved"
    REJECTED = "rejected"
    DRAFTED = "drafted"
    SENT = "sent"
    BOUNCED = "bounced"
    CANCELLED = "cancelled"


class InboundCategory(StrEnum):
    POSITIVE = "positive"
    QUESTION = "question"
    REFERRAL = "referral"
    OUT_OF_OFFICE = "out_of_office"
    UNSUBSCRIBE = "unsubscribe"
    HARD_BOUNCE = "hard_bounce"
    SOFT_BOUNCE = "soft_bounce"
    OTHER = "other"


class PolicyRule(StrEnum):
    ALLOW = "allow"
    ALLOW_WITH_FOOTER = "allow_with_footer"
    CONSENT_REQUIRED = "consent_required"
    BLOCK = "block"


class SuppressionKind(StrEnum):
    EMAIL = "email"
    DOMAIN = "domain"


class SuppressionReason(StrEnum):
    OPT_OUT = "opt_out"
    MANUAL = "manual"
    HARD_BOUNCE = "hard_bounce"
    COMPLAINT = "complaint"
    FORGET = "forget"


class ImportSource(StrEnum):
    CSV = "csv"
    XLSX = "xlsx"
    CLI = "cli"
    UI = "ui"
    WEBHOOK = "webhook"
    LEGACY_XLSX = "legacy_xlsx"


class ImportAnchor(StrEnum):
    DOMAIN = "domain"
    COMPANY_NAME = "company_name"
    EMAIL = "email"
    PERSON_COMPANY = "person_company"
    LINKEDIN_URL = "linkedin_url"


class ImportRowStatus(StrEnum):
    PENDING = "pending"
    NEEDS_CONFIRMATION = "needs_confirmation"
    ACCEPTED = "accepted"
    MERGED = "merged"
    REJECTED = "rejected"


class CampaignStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class MailboxGateway(StrEnum):
    IMAP = "imap"  # any IMAP account, with an app password
    GMAIL = "gmail"  # Google Workspace or Gmail, through the Gmail API (OAuth)
    GRAPH = "graph"  # Microsoft 365 or Outlook, through Microsoft Graph (OAuth)
    EMAILENGINE = "emailengine"
    SMARTLEAD = "smartlead"
    INSTANTLY = "instantly"


class MailboxStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"
    NEEDS_RECONNECT = "needs_reconnect"  # access expired or was revoked: sign in again


class CredentialPurpose(StrEnum):
    MAILBOX_OAUTH = "mailbox_oauth"  # access and refresh tokens
    MAILBOX_PASSWORD = "mailbox_password"  # noqa: S105  (a purpose name, not a password)
    INTAKE_WEBHOOK = "intake_webhook"  # the workspace's webhook signing secret


class RunKind(StrEnum):
    PIPELINE = "pipeline"
    SYNC = "sync"
    IMPORT = "import"
    BAKEOFF = "bakeoff"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CallOutcome(StrEnum):
    HIT = "hit"
    MISS = "miss"
    ERROR = "error"
    CACHE_HIT = "cache_hit"
    BLOCKED_BY_CAP = "blocked_by_cap"


class EntityType(StrEnum):
    COMPANY = "company"
    CONTACT = "contact"
    CONTACT_EMAIL = "contact_email"
    MESSAGE = "message"
    MAILBOX = "mailbox"
    WORKSPACE = "workspace"
    IMPORT_ROW = "import_row"


class PolicyStage(StrEnum):
    """The stages that check the country policy, in pipeline order.

    The operator can skip the policy for a lead *from* one of them onward
    (``companies.policy_skip_from``); a tail cannot contradict itself the way an arbitrary set
    could (copy skipped but deliver not would write an email deliver then withdraws).
    """

    GATE = "gate"
    CONTACTS = "contacts"
    EMAIL = "email"
    COPY = "copy"
    DELIVER = "deliver"


class WorkspaceStatus(StrEnum):
    """Whether a workspace may be used. Billing access (Phase 6d) is separate."""

    ACTIVE = "active"
    PAUSED = "paused"  # a platform admin stopped its engine; people can still sign in and read
    SUSPENDED = "suspended"  # a platform admin closed it; nobody can use it
    PENDING_DELETION = "pending_deletion"  # deletion asked for; can be restored until it is due
    DELETED = "deleted"  # purged; the row stays as a tombstone so cost history keeps its key


class MembershipRole(StrEnum):
    """A person's role in one workspace (Phase 6b)."""

    ADMIN = "admin"
    MEMBER = "member"


class PlatformRole(StrEnum):
    """Staff of the platform itself, separate from any workspace role."""

    ADMIN = "admin"  # runs the admin console; never sees lead content
    SUPERADMIN = "superadmin"  # alpha only: may also read every workspace


class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class AuthTokenPurpose(StrEnum):
    INVITE = "invite"
    RESET = "reset"
