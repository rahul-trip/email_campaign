"""Workspaces get a slug and a status (Phase 6a).

1. ``workspaces.slug``: the short, unique, URL-safe name a workspace is reached by
   (``/w/<slug>``), made from the name for existing rows.
2. ``workspaces.status``: ``active``, ``paused``, ``suspended``, ``pending_deletion`` or
   ``deleted`` (the domain state machine ``WORKSPACE`` says which moves are allowed), and
   ``deletion_due_at`` for a workspace waiting to be purged.
3. Names are no longer unique (two customers may share one), so ``uq_workspaces_name`` goes.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from outbound.domain.slugs import unique_slug

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = ("active", "paused", "suspended", "pending_deletion", "deleted")


def upgrade() -> None:
    with op.batch_alter_table("workspaces") as batch:
        batch.add_column(sa.Column("slug", sa.String(length=48), nullable=True))
        batch.add_column(
            sa.Column("status", sa.String(length=40), nullable=False, server_default="active")
        )
        batch.create_check_constraint(
            op.f("ck_workspaces_workspace_status"),
            sa.text("status IN (" + ", ".join(f"'{s}'" for s in STATUSES) + ")"),
        )
        batch.add_column(sa.Column("deletion_due_at", sa.DateTime(timezone=True), nullable=True))
    bind = op.get_bind()
    taken: set[str] = set()
    for workspace_id, name in bind.execute(sa.text("SELECT id, name FROM workspaces ORDER BY id")):
        slug = unique_slug(name, taken)
        taken.add(slug)
        bind.execute(
            sa.text("UPDATE workspaces SET slug = :slug WHERE id = :id"),
            {"slug": slug, "id": workspace_id},
        )
    with op.batch_alter_table("workspaces") as batch:
        batch.alter_column("slug", existing_type=sa.String(length=48), nullable=False)
        batch.create_unique_constraint("uq_workspaces_slug", ["slug"])
        batch.drop_constraint("uq_workspaces_name", type_="unique")


def downgrade() -> None:
    with op.batch_alter_table("workspaces") as batch:
        batch.create_unique_constraint("uq_workspaces_name", ["name"])
        batch.drop_constraint("uq_workspaces_slug", type_="unique")
        batch.drop_column("deletion_due_at")
        batch.drop_constraint(op.f("ck_workspaces_workspace_status"), type_="check")
        batch.drop_column("status")
        batch.drop_column("slug")
