"""Mailboxes each workspace connects itself, and encrypted credentials (Phase 6c).

1. ``mailboxes``: the gateways ``gmail`` and ``graph`` beside ``imap``; the status
   ``needs_reconnect``; who owns it (``owner_user_id``); one default sender per workspace
   (``is_default``, a partial unique index); the person who signs from it (``sender``); how to
   reach it (``connection``: host, port, folders); ``last_checked_at``. ``credentials_ref`` may be
   empty until the mailbox is connected.
2. ``credentials``: a tenant table of secrets, encrypted with AES-256-GCM. Only the ciphertext,
   its nonce and the key's version are stored; ``version`` makes a token refresh a
   compare-and-swap. Row-level security as on every tenant table (migration 0009).
3. ``campaigns.mailbox_id``: the campaign's sender, bound to the same workspace.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
WHEN = sa.DateTime(timezone=True)
APP, PLATFORM = "outbound_app", "outbound_platform"
KEY = "current_setting('app.workspace_id', true)"

GATEWAY = "ck_mailboxes_mailbox_gateway"
GATEWAYS_OLD = "'imap', 'emailengine', 'smartlead', 'instantly'"
GATEWAYS_NEW = "'imap', 'gmail', 'graph', 'emailengine', 'smartlead', 'instantly'"
STATUS = "ck_mailboxes_mailbox_status"
STATUSES_OLD = "'active', 'paused', 'error'"
STATUSES_NEW = STATUSES_OLD + ", 'needs_reconnect'"
PURPOSES = "'mailbox_oauth', 'mailbox_password', 'intake_webhook'"


def upgrade() -> None:
    with op.batch_alter_table("mailboxes") as batch:
        batch.drop_constraint(op.f(GATEWAY), type_="check")
        batch.create_check_constraint(op.f(GATEWAY), sa.text(f"gateway IN ({GATEWAYS_NEW})"))
        batch.drop_constraint(op.f(STATUS), type_="check")
        batch.create_check_constraint(op.f(STATUS), sa.text(f"status IN ({STATUSES_NEW})"))
        batch.alter_column("credentials_ref", existing_type=sa.String(length=200), nullable=True)
        batch.add_column(sa.Column("owner_user_id", sa.String(length=36), nullable=True))
        batch.add_column(
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(sa.Column("sender", JSON, nullable=True))
        batch.add_column(sa.Column("connection", JSON, nullable=True))
        batch.add_column(sa.Column("last_checked_at", WHEN, nullable=True))
        batch.create_foreign_key(
            op.f("fk_mailboxes_owner_user_id_users"),
            "users",
            ["owner_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ux_mailboxes_one_default",
        "mailboxes",
        ["workspace_id"],
        unique=True,
        sqlite_where=sa.text("is_default"),
        postgresql_where=sa.text("is_default"),
    )

    op.create_table(
        "credentials",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(length=12), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("expires_at", WHEN, nullable=True),
        sa.Column("details", JSON, nullable=True),
        sa.Column("created_at", WHEN, nullable=False),
        sa.Column("updated_at", WHEN, nullable=False),
        sa.CheckConstraint(
            f"purpose IN ({PURPOSES})", name=op.f("ck_credentials_credential_purpose")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name=op.f("fk_credentials_workspace_id_workspaces")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credentials")),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_credentials_workspace_id_id")),
        sa.UniqueConstraint("workspace_id", "name", name=op.f("uq_credentials_workspace_id_name")),
    )
    op.create_index(op.f("ix_credentials_workspace_id"), "credentials", ["workspace_id"])

    with op.batch_alter_table("campaigns") as batch:
        batch.add_column(sa.Column("mailbox_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            op.f("fk_campaigns_mailbox_id_mailboxes"),
            "mailboxes",
            ["workspace_id", "mailbox_id"],
            ["workspace_id", "id"],
        )

    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON credentials TO {APP}")
        op.execute("ALTER TABLE credentials ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_rows ON credentials FOR ALL TO {APP} "
            f"USING (workspace_id = {KEY}) WITH CHECK (workspace_id = {KEY})"
        )
        # The platform role never reads secrets, not even encrypted ones.


def downgrade() -> None:
    bind = op.get_bind()
    for column, value, allowed in (
        ("gateway", "gateway", GATEWAYS_OLD),
        ("status", "status", STATUSES_OLD),
    ):
        left = bind.execute(
            sa.text(f"SELECT count(*) FROM mailboxes WHERE {value} NOT IN ({allowed})")  # noqa: S608  (constants)
        ).scalar_one()
        if left:
            raise RuntimeError(f"{left} mailbox(es) use a {column} older code does not know")
    with op.batch_alter_table("campaigns") as batch:
        batch.drop_constraint(op.f("fk_campaigns_mailbox_id_mailboxes"), type_="foreignkey")
        batch.drop_column("mailbox_id")
    op.drop_index(op.f("ix_credentials_workspace_id"), table_name="credentials")
    op.drop_table("credentials")
    op.drop_index("ux_mailboxes_one_default", table_name="mailboxes")
    with op.batch_alter_table("mailboxes") as batch:
        batch.drop_constraint(op.f("fk_mailboxes_owner_user_id_users"), type_="foreignkey")
        batch.drop_column("last_checked_at")
        batch.drop_column("connection")
        batch.drop_column("sender")
        batch.drop_column("is_default")
        batch.drop_column("owner_user_id")
        batch.alter_column("credentials_ref", existing_type=sa.String(length=200), nullable=False)
        batch.drop_constraint(op.f(STATUS), type_="check")
        batch.create_check_constraint(op.f(STATUS), sa.text(f"status IN ({STATUSES_OLD})"))
        batch.drop_constraint(op.f(GATEWAY), type_="check")
        batch.create_check_constraint(op.f(GATEWAY), sa.text(f"gateway IN ({GATEWAYS_OLD})"))
