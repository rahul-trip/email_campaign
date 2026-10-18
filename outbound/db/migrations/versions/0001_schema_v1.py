"""Schema v1: the 17 tables of docs/SCHEMA.md.

Frozen: it imports nothing from the application, so later changes to the models cannot alter
what this revision builds. Every enum column is text with one named CHECK constraint.

Revision ID: 0001
Revises:
Create Date: 2026-10-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "sender_profile",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "settings",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspaces")),
    )
    op.create_table(
        "campaigns",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "target_titles",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("icp_description", sa.Text(), nullable=True),
        sa.Column("min_fit_score", sa.Integer(), nullable=False),
        sa.Column(
            "research_questions",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "cadence_days",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'paused', 'archived')", name=op.f("ck_campaigns_campaign_status")
        ),
        sa.CheckConstraint(
            "min_fit_score BETWEEN 0 AND 100", name=op.f("ck_campaigns_min_fit_score_range")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_campaigns_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campaigns")),
        sa.UniqueConstraint("workspace_id", "name", name=op.f("uq_campaigns_workspace_id_name")),
    )
    with op.batch_alter_table("campaigns", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_campaigns_workspace_id"), ["workspace_id"], unique=False
        )

    op.create_table(
        "country_policies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("rule", sa.String(length=40), nullable=False),
        sa.Column("requires_corporate_subscriber", sa.Boolean(), nullable=False),
        sa.Column(
            "allowed_provenance",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("footer_template", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("reviewed_by", sa.String(length=200), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "rule IN ('allow', 'allow_with_footer', 'consent_required', 'block')",
            name=op.f("ck_country_policies_policy_rule"),
        ),
        sa.CheckConstraint(
            "length(country_code) = 2", name=op.f("ck_country_policies_country_code_length")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_country_policies_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_country_policies")),
        sa.UniqueConstraint(
            "workspace_id",
            "country_code",
            name=op.f("uq_country_policies_workspace_id_country_code"),
        ),
    )
    with op.batch_alter_table("country_policies", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_country_policies_workspace_id"), ["workspace_id"], unique=False
        )

    op.create_table(
        "events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("type", sa.String(length=60), nullable=False),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column(
            "data",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "entity_type IN ('company', 'contact', 'contact_email', 'message', 'mailbox', 'workspace', 'import_row')",
            name=op.f("ck_events_entity_type"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_events_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
    )
    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.create_index(
            "ix_events_entity",
            ["workspace_id", "entity_type", "entity_id", "created_at"],
            unique=False,
        )
        batch_op.create_index(batch_op.f("ix_events_workspace_id"), ["workspace_id"], unique=False)

    op.create_table(
        "mailboxes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("address", sa.String(length=320), nullable=False),
        sa.Column("gateway", sa.String(length=40), nullable=False),
        sa.Column("credentials_ref", sa.String(length=200), nullable=False),
        sa.Column("sending_domain", sa.String(length=255), nullable=False),
        sa.Column(
            "dns_check",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("warmup_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("daily_cap", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "gateway IN ('imap', 'emailengine', 'smartlead', 'instantly')",
            name=op.f("ck_mailboxes_mailbox_gateway"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'paused', 'error')", name=op.f("ck_mailboxes_mailbox_status")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_mailboxes_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mailboxes")),
        sa.UniqueConstraint(
            "workspace_id", "address", name=op.f("uq_mailboxes_workspace_id_address")
        ),
    )
    with op.batch_alter_table("mailboxes", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_mailboxes_workspace_id"), ["workspace_id"], unique=False
        )

    op.create_table(
        "runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column(
            "params",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column(
            "counts",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("cost_micro_usd", sa.BigInteger(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('pipeline', 'sync', 'import', 'bakeoff')", name=op.f("ck_runs_run_kind")
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name=op.f("ck_runs_run_status"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_runs_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runs")),
    )
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_runs_workspace_id"), ["workspace_id"], unique=False)

    op.create_table(
        "suppressions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("value_hash", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('email', 'domain')", name=op.f("ck_suppressions_suppression_kind")
        ),
        sa.CheckConstraint(
            "reason IN ('opt_out', 'manual', 'hard_bounce', 'complaint', 'forget')",
            name=op.f("ck_suppressions_suppression_reason"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_suppressions_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_suppressions")),
        sa.UniqueConstraint(
            "workspace_id",
            "kind",
            "value_hash",
            name=op.f("uq_suppressions_workspace_id_kind_value_hash"),
        ),
    )
    with op.batch_alter_table("suppressions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_suppressions_workspace_id"), ["workspace_id"], unique=False
        )

    op.create_table(
        "companies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("campaign_id", sa.String(length=36), nullable=True),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("legal_entity_type", sa.String(length=40), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("hold_reason", sa.String(length=40), nullable=True),
        sa.Column("failed_stage", sa.String(length=40), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_action_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fit_score", sa.Integer(), nullable=True),
        sa.Column("fit_reason", sa.Text(), nullable=True),
        sa.Column("email_pattern", sa.String(length=100), nullable=True),
        sa.Column(
            "research",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column(
            "research_answers",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column(
            "policy_decision",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column(
            "manual_fields",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "hold_reason IN ('catch_all_unverified', 'catch_all_resolving', 'consent_required', 'country_unknown', 'entity_unknown', 'needs_operator')",
            name=op.f("ck_companies_hold_reason"),
        ),
        sa.CheckConstraint(
            "legal_entity_type IN ('corporate_subscriber', 'sole_trader_or_partnership', 'unknown')",
            name=op.f("ck_companies_legal_entity_type"),
        ),
        sa.CheckConstraint(
            "source IN ('manual', 'discovery', 'import', 'referral')",
            name=op.f("ck_companies_company_source"),
        ),
        sa.CheckConstraint(
            "status IN ('new', 'researched', 'qualified', 'disqualified', 'contacts_found', 'email_ready', 'held', 'copy_ready', 'approved', 'rejected', 'in_sequence', 'replied', 'completed', 'suppressed', 'failed')",
            name=op.f("ck_companies_company_status"),
        ),
        sa.CheckConstraint(
            "country_code IS NULL OR length(country_code) = 2",
            name=op.f("ck_companies_country_length"),
        ),
        sa.CheckConstraint(
            "fit_score IS NULL OR fit_score BETWEEN 0 AND 100",
            name=op.f("ck_companies_fit_score_range"),
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["campaigns.id"], name=op.f("fk_companies_campaign_id_campaigns")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_companies_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_companies")),
        sa.UniqueConstraint(
            "workspace_id", "domain", name=op.f("uq_companies_workspace_id_domain")
        ),
    )
    with op.batch_alter_table("companies", schema=None) as batch_op:
        batch_op.create_index(
            "ix_companies_queue", ["workspace_id", "status", "next_action_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_companies_workspace_id"), ["workspace_id"], unique=False
        )

    op.create_table(
        "import_batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("campaign_id", sa.String(length=36), nullable=True),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("filename", sa.String(length=500), nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column(
            "counts",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source IN ('csv', 'xlsx', 'cli', 'ui', 'webhook', 'legacy_xlsx')",
            name=op.f("ck_import_batches_import_source"),
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["campaigns.id"], name=op.f("fk_import_batches_campaign_id_campaigns")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_import_batches_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_batches")),
    )
    with op.batch_alter_table("import_batches", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_import_batches_workspace_id"), ["workspace_id"], unique=False
        )

    op.create_table(
        "contacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("full_name", sa.String(length=300), nullable=True),
        sa.Column("first_name", sa.String(length=150), nullable=True),
        sa.Column("last_name", sa.String(length=150), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("seniority", sa.String(length=100), nullable=True),
        sa.Column("linkedin_url", sa.String(length=500), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column(
            "manual_fields",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source IN ('operator', 'site', 'search', 'database', 'referral', 'ooo_alternate')",
            name=op.f("ck_contacts_contact_source"),
        ),
        sa.CheckConstraint(
            "status IN ('candidate', 'active', 'bounced', 'referred_away', 'opted_out', 'forgotten')",
            name=op.f("ck_contacts_contact_status"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_contacts_company_id_companies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_contacts_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contacts")),
    )
    with op.batch_alter_table("contacts", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_contacts_workspace_id"), ["workspace_id"], unique=False
        )
        batch_op.create_index(
            "ux_contacts_linkedin",
            ["workspace_id", "linkedin_url"],
            unique=True,
            sqlite_where=sa.text("linkedin_url IS NOT NULL"),
            postgresql_where=sa.text("linkedin_url IS NOT NULL"),
        )

    op.create_table(
        "import_rows",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=True),
        sa.Column(
            "raw",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("anchor", sa.String(length=40), nullable=False),
        sa.Column("resolved_domain", sa.String(length=255), nullable=True),
        sa.Column("resolution_confidence", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("company_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "anchor IN ('domain', 'company_name', 'email', 'person_company', 'linkedin_url')",
            name=op.f("ck_import_rows_import_anchor"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'needs_confirmation', 'accepted', 'merged', 'rejected')",
            name=op.f("ck_import_rows_import_row_status"),
        ),
        sa.CheckConstraint(
            "resolution_confidence BETWEEN 0 AND 1",
            name=op.f("ck_import_rows_resolution_confidence_range"),
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["import_batches.id"],
            name=op.f("fk_import_rows_batch_id_import_batches"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_import_rows_company_id_companies")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_import_rows_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_rows")),
    )
    with op.batch_alter_table("import_rows", schema=None) as batch_op:
        batch_op.create_index("ix_import_rows_status", ["workspace_id", "status"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_import_rows_workspace_id"), ["workspace_id"], unique=False
        )

    op.create_table(
        "consents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("contact_id", sa.String(length=36), nullable=False),
        sa.Column("basis", sa.String(length=40), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("recorded_by", sa.String(length=200), nullable=False),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "basis IN ('express', 'conspicuous_publication', 'voluntary_disclosure', 'existing_relationship')",
            name=op.f("ck_consents_consent_basis"),
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contacts.id"],
            name=op.f("fk_consents_contact_id_contacts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_consents_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consents")),
    )
    with op.batch_alter_table("consents", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_consents_workspace_id"), ["workspace_id"], unique=False
        )

    op.create_table(
        "contact_emails",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("contact_id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("provenance", sa.String(length=40), nullable=False),
        sa.Column("found_by", sa.String(length=100), nullable=True),
        sa.Column("verified_by", sa.String(length=100), nullable=True),
        sa.Column("resolution_ref", sa.String(length=300), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "provenance IN ('operator_given', 'publicly_published', 'api_database', 'pattern_inferred', 'referral')",
            name=op.f("ck_contact_emails_email_provenance"),
        ),
        sa.CheckConstraint(
            "status IN ('unverified', 'valid', 'catch_all_resolved', 'catch_all_pending', 'catch_all_unverified', 'unknown', 'invalid')",
            name=op.f("ck_contact_emails_email_status"),
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contacts.id"],
            name=op.f("fk_contact_emails_contact_id_contacts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_contact_emails_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_emails")),
        sa.UniqueConstraint(
            "workspace_id", "email", name=op.f("uq_contact_emails_workspace_id_email")
        ),
    )
    with op.batch_alter_table("contact_emails", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_contact_emails_workspace_id"), ["workspace_id"], unique=False
        )
        batch_op.create_index(
            "ux_contact_emails_primary",
            ["contact_id"],
            unique=True,
            sqlite_where=sa.text("is_primary"),
            postgresql_where=sa.text("is_primary"),
        )

    op.create_table(
        "notes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("contact_id", sa.String(length=36), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("author", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source IN ('operator', 'import', 'referral', 'reply', 'system')",
            name=op.f("ck_notes_note_source"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_notes_company_id_companies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"], name=op.f("fk_notes_contact_id_contacts")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_notes_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notes")),
    )
    with op.batch_alter_table("notes", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_notes_workspace_id"), ["workspace_id"], unique=False)

    op.create_table(
        "provider_calls",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("company_id", sa.String(length=36), nullable=True),
        sa.Column("contact_id", sa.String(length=36), nullable=True),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("operation", sa.String(length=100), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=40), nullable=False),
        sa.Column(
            "response",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("cost_micro_usd", sa.BigInteger(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('hit', 'miss', 'error', 'cache_hit', 'blocked_by_cap')",
            name=op.f("ck_provider_calls_call_outcome"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_provider_calls_company_id_companies")
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"], name=op.f("fk_provider_calls_contact_id_contacts")
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_provider_calls_run_id_runs")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_provider_calls_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_calls")),
    )
    with op.batch_alter_table("provider_calls", schema=None) as batch_op:
        batch_op.create_index(
            "ix_provider_calls_cache",
            ["workspace_id", "provider", "operation", "request_hash", "created_at"],
            unique=False,
        )
        batch_op.create_index(
            "ix_provider_calls_spend", ["workspace_id", "created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_provider_calls_workspace_id"), ["workspace_id"], unique=False
        )

    op.create_table(
        "messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("contact_id", sa.String(length=36), nullable=False),
        sa.Column("contact_email_id", sa.String(length=36), nullable=False),
        sa.Column("mailbox_id", sa.String(length=36), nullable=True),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column(
            "snippets",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("generated_body", sa.Text(), nullable=False),
        sa.Column("final_body", sa.Text(), nullable=True),
        sa.Column("edit_distance", sa.Float(), nullable=True),
        sa.Column(
            "lint_report",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("state", sa.String(length=40), nullable=False),
        sa.Column("remote_draft_id", sa.String(length=300), nullable=True),
        sa.Column("rfc_message_id", sa.String(length=500), nullable=True),
        sa.Column("in_reply_to", sa.String(length=500), nullable=True),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('generated', 'approved', 'rejected', 'drafted', 'sent', 'bounced', 'cancelled')",
            name=op.f("ck_messages_message_state"),
        ),
        sa.CheckConstraint("step BETWEEN 0 AND 2", name=op.f("ck_messages_step_range")),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_messages_company_id_companies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["contact_email_id"],
            ["contact_emails.id"],
            name=op.f("fk_messages_contact_email_id_contact_emails"),
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"], name=op.f("fk_messages_contact_id_contacts")
        ),
        sa.ForeignKeyConstraint(
            ["mailbox_id"], ["mailboxes.id"], name=op.f("fk_messages_mailbox_id_mailboxes")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_messages_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_messages")),
        sa.UniqueConstraint(
            "company_id", "contact_id", "step", name=op.f("uq_messages_company_id_contact_id_step")
        ),
    )
    with op.batch_alter_table("messages", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_messages_workspace_id"), ["workspace_id"], unique=False
        )
        batch_op.create_index(
            "ux_messages_rfc",
            ["workspace_id", "rfc_message_id"],
            unique=True,
            sqlite_where=sa.text("rfc_message_id IS NOT NULL"),
            postgresql_where=sa.text("rfc_message_id IS NOT NULL"),
        )

    op.create_table(
        "inbound_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("mailbox_id", sa.String(length=36), nullable=False),
        sa.Column("message_id", sa.String(length=36), nullable=True),
        sa.Column("company_id", sa.String(length=36), nullable=True),
        sa.Column("contact_id", sa.String(length=36), nullable=True),
        sa.Column("rfc_message_id", sa.String(length=500), nullable=False),
        sa.Column("from_address", sa.String(length=320), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("body_excerpt", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "extracted",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "category IN ('positive', 'question', 'referral', 'out_of_office', 'unsubscribe', 'hard_bounce', 'soft_bounce', 'other')",
            name=op.f("ck_inbound_messages_inbound_category"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_inbound_messages_company_id_companies")
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"], name=op.f("fk_inbound_messages_contact_id_contacts")
        ),
        sa.ForeignKeyConstraint(
            ["mailbox_id"], ["mailboxes.id"], name=op.f("fk_inbound_messages_mailbox_id_mailboxes")
        ),
        sa.ForeignKeyConstraint(
            ["message_id"], ["messages.id"], name=op.f("fk_inbound_messages_message_id_messages")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_inbound_messages_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inbound_messages")),
        sa.UniqueConstraint(
            "workspace_id",
            "rfc_message_id",
            name=op.f("uq_inbound_messages_workspace_id_rfc_message_id"),
        ),
    )
    with op.batch_alter_table("inbound_messages", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_inbound_messages_workspace_id"), ["workspace_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("inbound_messages", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_inbound_messages_workspace_id"))

    op.drop_table("inbound_messages")
    with op.batch_alter_table("messages", schema=None) as batch_op:
        batch_op.drop_index(
            "ux_messages_rfc",
            sqlite_where=sa.text("rfc_message_id IS NOT NULL"),
            postgresql_where=sa.text("rfc_message_id IS NOT NULL"),
        )
        batch_op.drop_index(batch_op.f("ix_messages_workspace_id"))

    op.drop_table("messages")
    with op.batch_alter_table("provider_calls", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_provider_calls_workspace_id"))
        batch_op.drop_index("ix_provider_calls_spend")
        batch_op.drop_index("ix_provider_calls_cache")

    op.drop_table("provider_calls")
    with op.batch_alter_table("notes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_notes_workspace_id"))

    op.drop_table("notes")
    with op.batch_alter_table("contact_emails", schema=None) as batch_op:
        batch_op.drop_index(
            "ux_contact_emails_primary",
            sqlite_where=sa.text("is_primary"),
            postgresql_where=sa.text("is_primary"),
        )
        batch_op.drop_index(batch_op.f("ix_contact_emails_workspace_id"))

    op.drop_table("contact_emails")
    with op.batch_alter_table("consents", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_consents_workspace_id"))

    op.drop_table("consents")
    with op.batch_alter_table("import_rows", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_import_rows_workspace_id"))
        batch_op.drop_index("ix_import_rows_status")

    op.drop_table("import_rows")
    with op.batch_alter_table("contacts", schema=None) as batch_op:
        batch_op.drop_index(
            "ux_contacts_linkedin",
            sqlite_where=sa.text("linkedin_url IS NOT NULL"),
            postgresql_where=sa.text("linkedin_url IS NOT NULL"),
        )
        batch_op.drop_index(batch_op.f("ix_contacts_workspace_id"))

    op.drop_table("contacts")
    with op.batch_alter_table("import_batches", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_import_batches_workspace_id"))

    op.drop_table("import_batches")
    with op.batch_alter_table("companies", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_companies_workspace_id"))
        batch_op.drop_index("ix_companies_queue")

    op.drop_table("companies")
    with op.batch_alter_table("suppressions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_suppressions_workspace_id"))

    op.drop_table("suppressions")
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_runs_workspace_id"))

    op.drop_table("runs")
    with op.batch_alter_table("mailboxes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_mailboxes_workspace_id"))

    op.drop_table("mailboxes")
    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_events_workspace_id"))
        batch_op.drop_index("ix_events_entity")

    op.drop_table("events")
    with op.batch_alter_table("country_policies", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_country_policies_workspace_id"))

    op.drop_table("country_policies")
    with op.batch_alter_table("campaigns", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_campaigns_workspace_id"))

    op.drop_table("campaigns")
    op.drop_table("workspaces")
