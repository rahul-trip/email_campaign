"""Join codes, join requests and in-app notifications.

- ``workspaces.join_code``: what a signed-in person types to ask to join.
- ``join_requests`` and ``notifications``: platform tables (no row-level security), reached
  only through ``outbound.db.identity``.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from outbound.domain.join_codes import new_join_code

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
WHEN = sa.DateTime(timezone=True)
APP, PLATFORM = "outbound_app", "outbound_platform"
ROLES = "'admin', 'member'"


def _id() -> sa.Column:  # type: ignore[type-arg]
    return sa.Column("id", sa.String(length=36), nullable=False)


def upgrade() -> None:
    bind = op.get_bind()
    with op.batch_alter_table("workspaces") as batch:
        batch.add_column(sa.Column("join_code", sa.String(length=16), nullable=True))
    taken: set[str] = set()
    for (workspace_id,) in bind.execute(sa.text("SELECT id FROM workspaces")).all():
        code = new_join_code()
        while code in taken:
            code = new_join_code()
        taken.add(code)
        bind.execute(
            sa.text("UPDATE workspaces SET join_code = :code WHERE id = :id"),
            {"code": code, "id": workspace_id},
        )
    with op.batch_alter_table("workspaces") as batch:
        batch.create_unique_constraint(op.f("uq_workspaces_join_code"), ["join_code"])

    op.create_table(
        "join_requests",
        _id(),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=True),
        sa.Column("decided_by", sa.String(length=36), nullable=True),
        sa.Column("decided_at", WHEN, nullable=True),
        sa.Column("created_at", WHEN, nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name=op.f("ck_join_requests_join_request_status"),
        ),
        sa.CheckConstraint(
            f"role IS NULL OR role IN ({ROLES})", name=op.f("ck_join_requests_granted_role")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_join_requests_workspace_id_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_join_requests_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_join_requests")),
    )
    op.create_index(op.f("ix_join_requests_workspace_id"), "join_requests", ["workspace_id"])
    op.create_index(op.f("ix_join_requests_user_id"), "join_requests", ["user_id"])
    op.create_index(
        "uq_join_requests_open",
        "join_requests",
        ["workspace_id", "user_id"],
        unique=True,
        sqlite_where=sa.text("status = 'pending'"),
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "notifications",
        _id(),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=True),
        sa.Column("data", JSON, nullable=False),
        sa.Column("read_at", WHEN, nullable=True),
        sa.Column("created_at", WHEN, nullable=False),
        sa.CheckConstraint(
            "kind IN ('join_requested', 'join_approved', 'join_rejected')",
            name=op.f("ck_notifications_notification_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notifications_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_notifications_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    op.create_index("ix_notifications_user", "notifications", ["user_id", "created_at"])

    if bind.dialect.name == "postgresql":
        for table in ("join_requests", "notifications"):
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP}, {PLATFORM}")


def downgrade() -> None:
    op.drop_table("notifications")
    op.drop_table("join_requests")
    with op.batch_alter_table("workspaces") as batch:
        batch.drop_constraint(op.f("uq_workspaces_join_code"), type_="unique")
        batch.drop_column("join_code")
