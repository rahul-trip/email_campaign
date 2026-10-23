"""Users, workspace memberships, invitations, password resets, sessions and the audit log
(Phase 6b).

These are platform tables, not tenant tables: no row-level security. They are reached only
through ``outbound.db.identity``, every query with an explicit predicate. On Postgres the app
and platform roles get the grants they need; the audit log is insert and read only.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
ROLES = "'admin', 'member'"
WHEN = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("password_hash", sa.String(length=300), nullable=False),
        sa.Column("platform_role", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("last_login_at", WHEN, nullable=True),
        sa.Column("terms_version", sa.String(length=40), nullable=True),
        sa.Column("terms_accepted_at", WHEN, nullable=True),
        sa.Column("created_at", WHEN, nullable=False),
        sa.Column("updated_at", WHEN, nullable=False),
        sa.CheckConstraint(
            "platform_role IN ('admin', 'superadmin')", name=op.f("ck_users_platform_role")
        ),
        sa.CheckConstraint("status IN ('active', 'disabled')", name=op.f("ck_users_user_status")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "memberships",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("created_at", WHEN, nullable=False),
        sa.Column("updated_at", WHEN, nullable=False),
        sa.CheckConstraint(f"role IN ({ROLES})", name=op.f("ck_memberships_membership_role")),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_memberships_workspace_id_workspaces")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name=op.f("fk_memberships_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memberships")),
        sa.UniqueConstraint(
            "workspace_id", "user_id", name=op.f("uq_memberships_workspace_id_user_id")
        ),
    )
    op.create_index(op.f("ix_memberships_workspace_id"), "memberships", ["workspace_id"])
    op.create_index(op.f("ix_memberships_user_id"), "memberships", ["user_id"])
    op.create_table(
        "auth_tokens",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=True),
        sa.Column("role", sa.String(length=40), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", WHEN, nullable=False),
        sa.Column("used_at", WHEN, nullable=True),
        sa.Column("revoked_at", WHEN, nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", WHEN, nullable=False),
        sa.CheckConstraint(
            "purpose IN ('invite', 'reset')", name=op.f("ck_auth_tokens_auth_token_purpose")
        ),
        sa.CheckConstraint(f"role IN ({ROLES})", name=op.f("ck_auth_tokens_invite_role")),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_auth_tokens_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_auth_tokens_token_hash")),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", WHEN, nullable=False),
        sa.Column("last_seen_at", WHEN, nullable=False),
        sa.Column("expires_at", WHEN, nullable=False),
        sa.Column("revoked_at", WHEN, nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.Column("data", JSON, nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE", name=op.f("fk_sessions_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sessions_token_hash")),
    )
    op.create_index(op.f("ix_sessions_user_id"), "sessions", ["user_id"])
    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", WHEN, nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("target_type", sa.String(length=40), nullable=True),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("data", JSON, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index("ix_audit_log_workspace", "audit_log", ["workspace_id", "created_at"])
    if op.get_bind().dialect.name == "postgresql":
        for table in ("users", "memberships", "auth_tokens", "sessions"):
            op.execute(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} "
                "TO outbound_app, outbound_platform"
            )
        op.execute("GRANT SELECT, INSERT ON audit_log TO outbound_app, outbound_platform")


def downgrade() -> None:
    op.drop_index("ix_audit_log_workspace", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index(op.f("ix_sessions_user_id"), table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("auth_tokens")
    op.drop_index(op.f("ix_memberships_user_id"), table_name="memberships")
    op.drop_index(op.f("ix_memberships_workspace_id"), table_name="memberships")
    op.drop_table("memberships")
    op.drop_table("users")
