"""The startup self-check for tenant isolation on Postgres (Phase 6a).

Row-level security only protects a connection that is subject to it. The owner of a table, a
superuser and a BYPASSRLS role all see every workspace, so ``serve`` and ``worker`` check what
they are connected as before taking any work, and refuse in production. The same check also
confirms every tenant table has row-level security on, and that Supabase's public Data API
roles hold no grants.
"""

from __future__ import annotations

from sqlalchemy import Engine, text

from outbound.db.base import Base

PUBLIC_API_ROLES = ("anon", "authenticated")

# Platform tables that name a workspace but are not one workspace's data: they are reached only
# through outbound.db.identity, with explicit predicates, and have no row-level security.
PLATFORM_TABLES = frozenset({"memberships", "auth_tokens", "audit_log"})


def tenant_tables() -> tuple[str, ...]:
    """Every table whose rows belong to one workspace, plus ``workspaces`` itself."""
    scoped = (
        t.name
        for t in Base.metadata.sorted_tables
        if "workspace_id" in t.columns and t.name not in PLATFORM_TABLES
    )
    return (*sorted(scoped), "workspaces")


def isolation_problems(engine: Engine) -> list[str]:
    """What would let one workspace see another's rows over this connection. SQLite: none."""
    if engine.dialect.name != "postgresql":
        return []
    problems = []
    tables = list(tenant_tables())
    with engine.connect() as connection:
        user, superuser, bypass = connection.execute(
            text(
                "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles "
                "WHERE rolname = current_user"
            )
        ).one()
        if superuser:
            problems.append(f"connected as {user}, a superuser, which ignores row-level security")
        if bypass:
            problems.append(f"connected as {user}, which has BYPASSRLS")
        owned = connection.execute(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                "AND tableowner = current_user AND tablename = ANY(:tables)"
            ),
            {"tables": tables},
        ).scalars()
        owned_list = sorted(owned)
        if owned_list:
            problems.append(
                f"connected as {user}, the owner of {', '.join(owned_list[:3])}"
                f"{'…' if len(owned_list) > 3 else ''}: owners are not subject to row-level "
                "security. Connect as outbound_app"
            )
        unprotected = connection.execute(
            text(
                "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relname = ANY(:tables) "
                "AND NOT c.relrowsecurity"
            ),
            {"tables": tables},
        ).scalars()
        for table in sorted(unprotected):
            problems.append(f"row-level security is off on {table}: run `outbound db upgrade`")
        # has_table_privilege, not information_schema: the latter only lists grants the
        # current user can see, which would hide anon's from outbound_app.
        exposed = connection.execute(
            text(
                "SELECT DISTINCT r.rolname FROM pg_roles r, unnest(CAST(:tables AS text[])) t "
                "WHERE r.rolname = ANY(:roles) AND has_table_privilege("
                "r.rolname, 'public.' || t, 'SELECT, INSERT, UPDATE, DELETE')"
            ),
            {"roles": list(PUBLIC_API_ROLES), "tables": tables},
        ).scalars()
        for role in sorted(exposed):
            problems.append(
                f"the {role} role can read or write tables (Supabase's Data API): "
                "revoke its grants (docs/DEPLOY.md §1.2)"
            )
    return problems
