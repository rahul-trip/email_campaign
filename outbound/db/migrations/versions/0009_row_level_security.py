"""Row-level security and least-privilege roles (Phase 6a). Postgres only; nothing on SQLite.

Two roles, created ``NOLOGIN`` if they are missing (passwords and ``LOGIN`` are set by hand,
never in a migration; see docs/DEPLOY.md):

- ``outbound_app``: the API and the worker. DML on tenant tables, seen only through the policy
  ``workspace_id = current_setting('app.workspace_id', true)``: a transaction sees and writes
  the rows of the one workspace its session set, and none at all if it set nothing.
- ``outbound_platform``: reads across workspaces (the scheduler, later the admin console).
  SELECT on tenant tables, through a read-only policy; writes only the ``workspaces`` table
  (and the platform tables later phases add). It has no BYPASSRLS.

The owner (whoever runs this migration) keeps owning the tables, so migrations and seeding
still work; ``serve`` and ``worker`` refuse to start connected as the owner, a superuser or a
BYPASSRLS role (``outbound.db.isolation``), which is why ``FORCE ROW LEVEL SECURITY`` is not
needed. Grants to Supabase's ``anon`` and ``authenticated`` roles, which its Data API uses, are
revoked where those roles exist.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-23
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP, PLATFORM = "outbound_app", "outbound_platform"

TENANT_TABLES = (
    "campaigns", "mailboxes", "country_policies", "suppressions", "import_batches",
    "import_rows", "companies", "contacts", "contact_emails", "notes", "consents", "messages",
    "inbound_messages", "runs", "provider_calls", "events",
)  # fmt: skip

KEY = "current_setting('app.workspace_id', true)"


def _create_role(name: str) -> None:
    op.execute(
        f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{name}') "
        f"THEN CREATE ROLE {name} NOLOGIN NOBYPASSRLS; END IF; END $$"
    )


def _revoke_public_api_roles() -> None:
    for role in ("anon", "authenticated"):
        op.execute(
            f"DO $$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN "  # noqa: S608  (role names are constants)
            f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}; "
            f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {role}; "
            f"REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM {role}; "
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM {role}; "
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM {role}; "
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM {role}; "
            "END IF; END $$"
        )


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    _create_role(APP)
    _create_role(PLATFORM)
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP}, {PLATFORM}")
    for table in TENANT_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP}")
        op.execute(f"GRANT SELECT ON {table} TO {PLATFORM}")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_rows ON {table} FOR ALL TO {APP} "
            f"USING (workspace_id = {KEY}) WITH CHECK (workspace_id = {KEY})"
        )
        op.execute(f"CREATE POLICY platform_read ON {table} FOR SELECT TO {PLATFORM} USING (true)")
    # A tenant sees and edits its own workspace row (its profile and settings), nothing else.
    op.execute(f"GRANT SELECT, UPDATE ON workspaces TO {APP}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON workspaces TO {PLATFORM}")
    op.execute("ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY own_workspace ON workspaces FOR ALL TO {APP} "
        f"USING (id = {KEY}) WITH CHECK (id = {KEY})"
    )
    op.execute(
        f"CREATE POLICY platform_all ON workspaces FOR ALL TO {PLATFORM} "
        "USING (true) WITH CHECK (true)"
    )
    _revoke_public_api_roles()


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP POLICY IF EXISTS own_workspace ON workspaces")
    op.execute("DROP POLICY IF EXISTS platform_all ON workspaces")
    op.execute("ALTER TABLE workspaces DISABLE ROW LEVEL SECURITY")
    op.execute(f"REVOKE ALL ON workspaces FROM {APP}, {PLATFORM}")
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_rows ON {table}")
        op.execute(f"DROP POLICY IF EXISTS platform_read ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON {table} FROM {APP}, {PLATFORM}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP}, {PLATFORM}")
