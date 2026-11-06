"""Companies discovery found for a campaign, and what it decided about each.

``discovery_candidates`` keeps every company a discovery run found (from the Y Combinator
directory, from articles and lists, ...), where it was found, what the source said about it,
its screening score and the verdict: accepted as a lead, rejected, unresolved (no confident
website), already a lead, or over the run's limit. One row per company per campaign, so no
company is screened twice. A tenant table with row-level security like the others; the app
role may read, add and update its own rows.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
WHEN = sa.DateTime(timezone=True)
APP, PLATFORM = "outbound_app", "outbound_platform"
KEY = "current_setting('app.workspace_id', true)"
VERDICTS = "'accepted', 'rejected', 'unresolved', 'already_lead', 'over_limit'"


def upgrade() -> None:
    op.create_table(
        "discovery_candidates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("campaign_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("name_key", sa.String(length=300), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=True),
        sa.Column("sources", JSON, nullable=False),
        sa.Column("source_urls", JSON, nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("screen_score", sa.Integer(), nullable=True),
        sa.Column("rank_score", sa.Integer(), nullable=True),
        sa.Column("verdict", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", WHEN, nullable=False),
        sa.Column("updated_at", WHEN, nullable=False),
        sa.CheckConstraint(
            f"verdict IN ({VERDICTS})", name=op.f("ck_discovery_candidates_candidate_verdict")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_discovery_candidates_workspace_id_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "campaign_id"],
            ["campaigns.workspace_id", "campaigns.id"],
            name=op.f("fk_discovery_candidates_campaign_id_campaigns"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_discovery_candidates")),
        sa.UniqueConstraint(
            "workspace_id",
            "campaign_id",
            "name_key",
            name=op.f("uq_discovery_candidates_workspace_id_campaign_id_name_key"),
        ),
    )
    op.create_index(
        op.f("ix_discovery_candidates_workspace_id"), "discovery_candidates", ["workspace_id"]
    )
    op.create_index(
        "ix_discovery_candidates_run", "discovery_candidates", ["workspace_id", "run_id"]
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON discovery_candidates TO {APP}")
        op.execute(f"GRANT SELECT ON discovery_candidates TO {PLATFORM}")
        op.execute("ALTER TABLE discovery_candidates ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_rows ON discovery_candidates FOR ALL TO {APP} "
            f"USING (workspace_id = {KEY}) WITH CHECK (workspace_id = {KEY})"
        )
        op.execute(
            f"CREATE POLICY platform_read ON discovery_candidates FOR SELECT TO {PLATFORM} "
            "USING (true)"
        )


def downgrade() -> None:
    op.drop_index("ix_discovery_candidates_run", table_name="discovery_candidates")
    op.drop_index(op.f("ix_discovery_candidates_workspace_id"), table_name="discovery_candidates")
    op.drop_table("discovery_candidates")
