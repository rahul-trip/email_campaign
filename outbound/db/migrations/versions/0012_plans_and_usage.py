"""Plans, overrides, credit grants and usage (Phase 6d).

1. ``workspace_plans``, ``entitlement_overrides``, ``credit_grants``: tenant tables the workspace
   can read and platform admins write. The app role gets SELECT only; the platform role may
   read and write them (row-level security, as on every tenant table).
2. ``usage_events``: one row per charge, append-only. The app role gets SELECT and INSERT. A
   partial unique index charges every step once per lead except ``rewrite``. The lead is not a
   foreign key, so deleting a lead cannot return its credits.
3. ``platform_settings``: one row of platform-wide JSON (the plan catalog and more). A platform
   table: every role may read it, only the platform role writes it.
4. ``companies.credit_wait_step``: set while a lead waits, in place, for a credit.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
WHEN = sa.DateTime(timezone=True)
APP, PLATFORM = "outbound_app", "outbound_platform"
KEY = "current_setting('app.workspace_id', true)"
STEPS = "'discovery', 'manual', 'research', 'email', 'copy', 'deliver', 'rewrite'"
ADMIN_WRITTEN = ("workspace_plans", "entitlement_overrides", "credit_grants")


def _tenant_columns() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", WHEN, nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "workspace_plans",
        *_tenant_columns(),
        sa.Column("updated_at", WHEN, nullable=False),
        sa.Column("plan_code", sa.String(length=60), nullable=False),
        sa.Column("started_at", WHEN, nullable=False),
        sa.Column("access_until", WHEN, nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_workspace_plans_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_plans")),
        sa.UniqueConstraint("workspace_id", name=op.f("uq_workspace_plans_workspace_id")),
    )
    op.create_index(op.f("ix_workspace_plans_workspace_id"), "workspace_plans", ["workspace_id"])

    op.create_table(
        "entitlement_overrides",
        *_tenant_columns(),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("value", JSON, nullable=False),
        sa.Column("expires_at", WHEN, nullable=True),
        sa.Column("revoked_at", WHEN, nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("set_by", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_entitlement_overrides_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entitlement_overrides")),
    )
    op.create_index(
        op.f("ix_entitlement_overrides_workspace_id"), "entitlement_overrides", ["workspace_id"]
    )

    op.create_table(
        "credit_grants",
        *_tenant_columns(),
        sa.Column("step", sa.String(length=40), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("expires_at", WHEN, nullable=True),
        sa.Column("revoked_at", WHEN, nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("granted_by", sa.String(length=36), nullable=True),
        sa.CheckConstraint("amount > 0", name=op.f("ck_credit_grants_amount_positive")),
        sa.CheckConstraint(f"step IN ({STEPS})", name=op.f("ck_credit_grants_usage_step")),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_credit_grants_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credit_grants")),
    )
    op.create_index(op.f("ix_credit_grants_workspace_id"), "credit_grants", ["workspace_id"])

    op.create_table(
        "usage_events",
        *_tenant_columns(),
        sa.Column("step", sa.String(length=40), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.CheckConstraint(f"step IN ({STEPS})", name=op.f("ck_usage_events_usage_step")),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_usage_events_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_events")),
    )
    op.create_index(op.f("ix_usage_events_workspace_id"), "usage_events", ["workspace_id"])
    op.create_index(
        "ux_usage_events_once_per_lead",
        "usage_events",
        ["workspace_id", "step", "company_id"],
        unique=True,
        sqlite_where=sa.text("step <> 'rewrite'"),
        postgresql_where=sa.text("step <> 'rewrite'"),
    )
    op.create_index(
        "ix_usage_events_period", "usage_events", ["workspace_id", "step", "created_at"]
    )

    op.create_table(
        "platform_settings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data", JSON, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", WHEN, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_settings")),
    )

    with op.batch_alter_table("companies") as batch:
        batch.add_column(sa.Column("credit_wait_step", sa.String(length=40), nullable=True))
        batch.create_check_constraint(
            op.f("ck_companies_usage_step"),
            sa.text(f"credit_wait_step IN ({STEPS})"),
        )

    if op.get_bind().dialect.name == "postgresql":
        _grant()


def _grant() -> None:
    for table in ADMIN_WRITTEN:
        op.execute(f"GRANT SELECT ON {table} TO {APP}")
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {PLATFORM}")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_rows ON {table} FOR SELECT TO {APP} USING (workspace_id = {KEY})"
        )
        op.execute(
            f"CREATE POLICY platform_all ON {table} FOR ALL TO {PLATFORM} "
            "USING (true) WITH CHECK (true)"
        )
    op.execute(f"GRANT SELECT, INSERT ON usage_events TO {APP}")
    op.execute(f"GRANT SELECT ON usage_events TO {PLATFORM}")
    op.execute("ALTER TABLE usage_events ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_rows ON usage_events FOR ALL TO {APP} "
        f"USING (workspace_id = {KEY}) WITH CHECK (workspace_id = {KEY})"
    )
    op.execute(f"CREATE POLICY platform_read ON usage_events FOR SELECT TO {PLATFORM} USING (true)")
    # A platform table: no workspace, so no policy; grants alone decide.
    op.execute(f"GRANT SELECT ON platform_settings TO {APP}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON platform_settings TO {PLATFORM}")


def downgrade() -> None:
    with op.batch_alter_table("companies") as batch:
        batch.drop_constraint(op.f("ck_companies_usage_step"), type_="check")
        batch.drop_column("credit_wait_step")
    op.drop_table("platform_settings")
    op.drop_index("ix_usage_events_period", table_name="usage_events")
    op.drop_index("ux_usage_events_once_per_lead", table_name="usage_events")
    op.drop_table("usage_events")
    op.drop_table("credit_grants")
    op.drop_table("entitlement_overrides")
    op.drop_table("workspace_plans")
