"""The verified lead directory (Phase 6g).

Platform tables: no workspace column and no row-level security; grants decide. The app role reads
the served facts (companies, people, emails) and may only insert observations, reports and
suppressions; it can read the report status and suppression hashes it needs to stop serving, never
who reported. The platform role may do everything. Also ``companies.skip_directory``.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
WHEN = sa.DateTime(timezone=True)
APP, PLATFORM = "outbound_app", "outbound_platform"
STATUS = "'verified', 'disputed', 'invalid'"
TARGET = "'email', 'person', 'company', 'pattern'"


def _id() -> sa.Column:  # type: ignore[type-arg]
    return sa.Column("id", sa.String(length=36), nullable=False)


def upgrade() -> None:
    op.create_table(
        "directory_companies",
        _id(),
        sa.Column("domain", sa.String(length=253), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("email_pattern", sa.String(length=100), nullable=True),
        sa.Column("pattern_confidence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("last_confirmed_at", WHEN, nullable=False),
        sa.CheckConstraint(
            f"status IN ({STATUS})", name=op.f("ck_directory_companies_directory_status")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_directory_companies")),
        sa.UniqueConstraint("domain", name=op.f("uq_directory_companies_domain")),
    )
    op.create_table(
        "directory_people",
        _id(),
        sa.Column("company_domain", sa.String(length=253), nullable=False),
        sa.Column("full_name", sa.String(length=300), nullable=False),
        sa.Column("first_name", sa.String(length=150), nullable=False),
        sa.Column("last_name", sa.String(length=150), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("linkedin_url", sa.String(length=500), nullable=True),
        sa.Column("employment_status", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("last_confirmed_at", WHEN, nullable=False),
        sa.CheckConstraint(
            "employment_status IN ('current', 'left', 'unknown')",
            name=op.f("ck_directory_people_employment_status"),
        ),
        sa.CheckConstraint(
            f"status IN ({STATUS})", name=op.f("ck_directory_people_directory_status")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_directory_people")),
        sa.UniqueConstraint(
            "company_domain",
            "first_name",
            "last_name",
            name=op.f("uq_directory_people_company_domain_first_name_last_name"),
        ),
    )
    op.create_index(
        op.f("ix_directory_people_company_domain"), "directory_people", ["company_domain"]
    )
    op.create_table(
        "directory_emails",
        _id(),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("person_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("provenance", sa.String(length=40), nullable=False),
        sa.Column("source", sa.String(length=60), nullable=False),
        sa.Column("verified_by", sa.String(length=60), nullable=True),
        sa.Column("verified_at", WHEN, nullable=False),
        sa.CheckConstraint(
            f"status IN ({STATUS})", name=op.f("ck_directory_emails_directory_status")
        ),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["directory_people.id"],
            name=op.f("fk_directory_emails_person_id_directory_people"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_directory_emails")),
        sa.UniqueConstraint("email", name=op.f("uq_directory_emails_email")),
    )
    op.create_index(op.f("ix_directory_emails_person_id"), "directory_emails", ["person_id"])
    op.create_table(
        "directory_observations",
        _id(),
        sa.Column("target_type", sa.String(length=40), nullable=False),
        sa.Column("target_key", sa.String(length=320), nullable=False),
        sa.Column("data", JSON, nullable=False),
        sa.Column("source", sa.String(length=60), nullable=False),
        sa.Column("observed_at", WHEN, nullable=False),
        sa.Column("contributor_workspace_id", sa.String(length=36), nullable=False),
        sa.Column("folded_at", WHEN, nullable=True),
        sa.CheckConstraint(
            f"target_type IN ({TARGET})", name=op.f("ck_directory_observations_directory_target")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_directory_observations")),
    )
    op.create_table(
        "directory_flags",
        _id(),
        sa.Column("target_type", sa.String(length=40), nullable=False),
        sa.Column("target_key", sa.String(length=320), nullable=False),
        sa.Column("field", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("created_at", WHEN, nullable=False),
        sa.Column("resolved_at", WHEN, nullable=True),
        sa.Column("reporter_workspace_id", sa.String(length=36), nullable=False),
        sa.CheckConstraint(
            f"target_type IN ({TARGET})", name=op.f("ck_directory_flags_directory_target")
        ),
        sa.CheckConstraint(
            "status IN ('open', 'confirmed', 'rejected')",
            name=op.f("ck_directory_flags_flag_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_directory_flags")),
    )
    op.create_table(
        "directory_suppressions",
        _id(),
        sa.Column("value_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", WHEN, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_directory_suppressions")),
        sa.UniqueConstraint("value_hash", name=op.f("uq_directory_suppressions_value_hash")),
    )
    with op.batch_alter_table("companies") as batch:
        batch.add_column(
            sa.Column("skip_directory", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    if op.get_bind().dialect.name == "postgresql":
        _grant()


def _grant() -> None:
    for table in ("directory_companies", "directory_people", "directory_emails"):
        op.execute(f"GRANT SELECT ON {table} TO {APP}")
    for table in ("directory_observations", "directory_flags", "directory_suppressions"):
        op.execute(f"GRANT INSERT ON {table} TO {APP}")
    # What stops a fact being served; never who reported or contributed it.
    op.execute(f"GRANT SELECT (target_type, target_key, status) ON directory_flags TO {APP}")
    op.execute(f"GRANT SELECT (value_hash) ON directory_suppressions TO {APP}")
    # Forgetting a person must clear what was observed or reported about their address at once.
    op.execute(f"GRANT SELECT (target_type, target_key) ON directory_observations TO {APP}")
    op.execute(f"GRANT DELETE ON directory_observations, directory_flags TO {APP}")
    for table in (
        "directory_companies",
        "directory_people",
        "directory_emails",
        "directory_observations",
        "directory_flags",
        "directory_suppressions",
    ):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {PLATFORM}")


def downgrade() -> None:
    with op.batch_alter_table("companies") as batch:
        batch.drop_column("skip_directory")
    for table in (
        "directory_suppressions",
        "directory_flags",
        "directory_observations",
        "directory_emails",
        "directory_people",
        "directory_companies",
    ):
        op.drop_table(table)
