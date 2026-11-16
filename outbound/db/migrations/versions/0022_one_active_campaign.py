"""One active campaign per workspace.

``campaigns.status`` always existed but nothing read it. From now on a workspace keeps any number
of campaigns and exactly one is active: discovery, new targets and the engine's work follow it,
and a paused campaign's leads wait. A partial unique index enforces it.

A workspace that has several active campaigns today keeps active the one with the most leads
(then the one that says who it is after, then the oldest) and the rest are paused.

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "uq_campaigns_one_active"


def upgrade() -> None:
    bind = op.get_bind()
    leads: dict[str, int] = dict(
        bind.execute(
            sa.text(
                "SELECT campaign_id, COUNT(*) FROM companies "
                "WHERE campaign_id IS NOT NULL GROUP BY campaign_id"
            )
        ).all()
    )
    active = bind.execute(
        sa.text(
            "SELECT id, workspace_id, icp_description, created_at FROM campaigns "
            "WHERE status = 'active'"
        )
    ).all()
    by_workspace: dict[str, list[tuple[str, bool, object]]] = {}
    for campaign_id, workspace_id, icp, created in active:
        by_workspace.setdefault(workspace_id, []).append(
            (campaign_id, bool((icp or "").strip()), created)
        )
    for rows in by_workspace.values():
        if len(rows) < 2:
            continue
        rows.sort(key=lambda r: (-int(leads.get(r[0], 0)), not r[1], str(r[2])))
        for campaign_id, _, _ in rows[1:]:
            bind.execute(
                sa.text("UPDATE campaigns SET status = 'paused' WHERE id = :id"),
                {"id": campaign_id},
            )
    op.create_index(
        INDEX,
        "campaigns",
        ["workspace_id"],
        unique=True,
        sqlite_where=sa.text("status = 'active'"),
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index(INDEX, table_name="campaigns")
