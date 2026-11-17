"""LinkedIn messages the operator pastes by hand, and the hold that follows sending one.

``linkedin_messages`` keeps, for each confirmed person, a connection note and a follow-up
message the engine wrote. Nothing in it is ever sent by the engine: the operator copies the text
into LinkedIn and says they did. Marking one sent holds the lead's email (``hold_reason``
``linkedin_contacted``) until the operator releases it. A tenant table with row-level security
like the others; the app role may read, add, change and delete its own rows.

The CHECKs on ``events.entity_type`` and ``companies.hold_reason`` are dropped and recreated by
name (see migration 0003). The downgrade refuses to run while a lead is held for LinkedIn or an
event names a LinkedIn message: turning them into anything else would be a guess.

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
WHEN = sa.DateTime(timezone=True)
APP, PLATFORM = "outbound_app", "outbound_platform"
KEY = "current_setting('app.workspace_id', true)"
STATES = "'drafted', 'sent', 'skipped'"

ENTITIES_OLD = (
    "'company', 'contact', 'contact_email', 'message', 'mailbox', 'workspace', 'import_row'"
)
ENTITIES_NEW = ENTITIES_OLD + ", 'linkedin_message'"
HOLDS_OLD = (
    "'catch_all_unverified', 'catch_all_resolving', 'consent_required', 'country_unknown', "
    "'entity_unknown', 'needs_operator'"
)
HOLDS_NEW = HOLDS_OLD + ", 'linkedin_contacted'"


def _swap(table: str, name: str, column: str, values: str) -> None:
    with op.batch_alter_table(table) as batch:
        batch.drop_constraint(op.f(name), type_="check")
        batch.create_check_constraint(op.f(name), sa.text(f"{column} IN ({values})"))


def upgrade() -> None:
    op.create_table(
        "linkedin_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("contact_id", sa.String(length=36), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=40), nullable=False),
        sa.Column("issues", JSON, nullable=False),
        sa.Column("edited", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("sent_at", WHEN, nullable=True),
        sa.Column("sent_by", sa.String(length=100), nullable=True),
        sa.Column("created_at", WHEN, nullable=False),
        sa.Column("updated_at", WHEN, nullable=False),
        sa.CheckConstraint(
            f"state IN ({STATES})", name=op.f("ck_linkedin_messages_linkedin_state")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_linkedin_messages_workspace_id_workspaces"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "company_id"],
            ["companies.workspace_id", "companies.id"],
            name=op.f("fk_linkedin_messages_company_id_companies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "contact_id"],
            ["contacts.workspace_id", "contacts.id"],
            name=op.f("fk_linkedin_messages_contact_id_contacts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_linkedin_messages")),
        sa.UniqueConstraint(
            "workspace_id", "contact_id", name=op.f("uq_linkedin_messages_workspace_id_contact_id")
        ),
    )
    op.create_index(
        op.f("ix_linkedin_messages_workspace_id"), "linkedin_messages", ["workspace_id"]
    )
    op.create_index("ix_linkedin_messages_state", "linkedin_messages", ["workspace_id", "state"])
    _swap("events", "ck_events_entity_type", "entity_type", ENTITIES_NEW)
    _swap("companies", "ck_companies_hold_reason", "hold_reason", HOLDS_NEW)
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON linkedin_messages TO {APP}")
        op.execute(f"GRANT SELECT ON linkedin_messages TO {PLATFORM}")
        op.execute("ALTER TABLE linkedin_messages ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_rows ON linkedin_messages FOR ALL TO {APP} "
            f"USING (workspace_id = {KEY}) WITH CHECK (workspace_id = {KEY})"
        )
        op.execute(
            f"CREATE POLICY platform_read ON linkedin_messages FOR SELECT TO {PLATFORM} "
            "USING (true)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    held = bind.execute(
        sa.text("SELECT count(*) FROM companies WHERE hold_reason = 'linkedin_contacted'")
    ).scalar_one()
    named = bind.execute(
        sa.text("SELECT count(*) FROM events WHERE entity_type = 'linkedin_message'")
    ).scalar_one()
    if held or named:
        raise RuntimeError(
            f"{held} lead(s) are held for LinkedIn and {named} event(s) name a LinkedIn message;"
            " release the leads and delete the events before downgrading"
        )
    _swap("events", "ck_events_entity_type", "entity_type", ENTITIES_OLD)
    _swap("companies", "ck_companies_hold_reason", "hold_reason", HOLDS_OLD)
    op.drop_index("ix_linkedin_messages_state", table_name="linkedin_messages")
    op.drop_index(op.f("ix_linkedin_messages_workspace_id"), table_name="linkedin_messages")
    op.drop_table("linkedin_messages")
