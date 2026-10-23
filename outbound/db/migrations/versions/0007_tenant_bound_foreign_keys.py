"""Foreign keys that also match the workspace (Phase 6a).

Every link between tenant tables becomes ``(workspace_id, x_id) → parent (workspace_id, id)``,
so the database itself refuses a row in one workspace that points at a row in another.
Foreign-key checks ignore row-level security, so without this a tenant could link to, probe
for, or block the deletes of another tenant's rows. Each key keeps its old name.

A pre-check stops the migration, naming the rows, if any cross-workspace link already exists.
On Postgres each key is added ``NOT VALID`` and then validated, so the write lock is short.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PARENTS = (
    "campaigns", "companies", "contact_emails", "contacts", "import_batches", "mailboxes",
    "messages", "runs",
)  # fmt: skip

# (child table, column, parent table, on delete)
KEYS: tuple[tuple[str, str, str, str | None], ...] = (
    ("import_batches", "campaign_id", "campaigns", None),
    ("import_rows", "batch_id", "import_batches", "CASCADE"),
    ("import_rows", "company_id", "companies", None),
    ("companies", "campaign_id", "campaigns", None),
    ("contacts", "company_id", "companies", "CASCADE"),
    ("contact_emails", "contact_id", "contacts", "CASCADE"),
    ("notes", "company_id", "companies", "CASCADE"),
    ("notes", "contact_id", "contacts", None),
    ("consents", "contact_id", "contacts", "CASCADE"),
    ("messages", "company_id", "companies", "CASCADE"),
    ("messages", "contact_id", "contacts", None),
    ("messages", "contact_email_id", "contact_emails", None),
    ("messages", "mailbox_id", "mailboxes", None),
    ("inbound_messages", "mailbox_id", "mailboxes", None),
    ("inbound_messages", "message_id", "messages", None),
    ("inbound_messages", "company_id", "companies", None),
    ("inbound_messages", "contact_id", "contacts", None),
    ("provider_calls", "run_id", "runs", None),
    ("provider_calls", "company_id", "companies", None),
    ("provider_calls", "contact_id", "contacts", None),
)


def _name(child: str, column: str, parent: str) -> str:
    return f"fk_{child}_{column}_{parent}"


def _precheck() -> None:
    bind = op.get_bind()
    found = []
    for child, column, parent, _ in KEYS:
        count = bind.execute(
            sa.text(
                f"SELECT COUNT(*) FROM {child} c JOIN {parent} p ON p.id = c.{column} "  # noqa: S608  (names are constants above)
                "WHERE p.workspace_id <> c.workspace_id"
            )
        ).scalar_one()
        if count:
            found.append(f"{child}.{column} → {parent}: {count} row(s)")
    if found:
        raise RuntimeError(
            "rows point into another workspace; fix them before migrating:\n  " + "\n  ".join(found)
        )


def upgrade() -> None:
    _precheck()
    for parent in PARENTS:
        with op.batch_alter_table(parent) as batch:
            batch.create_unique_constraint(f"uq_{parent}_workspace_id_id", ["workspace_id", "id"])
    postgres = op.get_bind().dialect.name == "postgresql"
    for child, column, parent, ondelete in KEYS:
        name = _name(child, column, parent)
        if postgres:
            cascade = f" ON DELETE {ondelete}" if ondelete else ""
            op.execute(f"ALTER TABLE {child} DROP CONSTRAINT {name}")
            op.execute(
                f"ALTER TABLE {child} ADD CONSTRAINT {name} FOREIGN KEY (workspace_id, {column}) "
                f"REFERENCES {parent} (workspace_id, id){cascade} NOT VALID"
            )
            op.execute(f"ALTER TABLE {child} VALIDATE CONSTRAINT {name}")
        else:
            with op.batch_alter_table(child) as batch:
                batch.drop_constraint(name, type_="foreignkey")
                batch.create_foreign_key(
                    name, parent, ["workspace_id", column], ["workspace_id", "id"],
                    ondelete=ondelete,
                )  # fmt: skip


def downgrade() -> None:
    for child, column, parent, ondelete in KEYS:
        name = _name(child, column, parent)
        with op.batch_alter_table(child) as batch:
            batch.drop_constraint(name, type_="foreignkey")
            batch.create_foreign_key(name, parent, [column], ["id"], ondelete=ondelete)
    for parent in PARENTS:
        with op.batch_alter_table(parent) as batch:
            batch.drop_constraint(f"uq_{parent}_workspace_id_id", type_="unique")
