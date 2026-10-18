"""Command line entry point: ``uv run outbound``."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from outbound.bootstrap import build_container
from outbound.cli import ops, profile, serve
from outbound.cli.common import DatabaseUrl, WorkspaceName, settings_for, workspace_id_or_exit
from outbound.cli.targets import targets_app
from outbound.db import migrate
from outbound.services import defaults
from outbound.services.legacy_import import LegacyWorkbookError, import_legacy_xlsx
from outbound.services.seed import seed_defaults

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Outbound engine commands.")
db_app = typer.Typer(no_args_is_help=True, help="Create and migrate the database.")
app.add_typer(db_app, name="db")
app.add_typer(targets_app, name="targets")
ops.register(app)
serve.register(app)
profile.register(app)


@db_app.command("upgrade")
def db_upgrade(
    revision: Annotated[str, typer.Argument(help="Target revision.")] = "head",
    database_url: DatabaseUrl = None,
) -> None:
    """Bring the database up to the latest schema."""
    url = settings_for(database_url).database_url
    migrate.upgrade(url, revision)
    typer.echo(f"database is at revision {migrate.current_revision(url)}")


@db_app.command("downgrade")
def db_downgrade(
    revision: Annotated[str, typer.Argument(help="Target revision, or -1 for one step.")] = "-1",
    database_url: DatabaseUrl = None,
) -> None:
    """Step the schema back (this can drop data)."""
    migrate.downgrade(settings_for(database_url).database_url, revision)
    typer.echo(f"moved back to {revision}")


@db_app.command("current")
def db_current(database_url: DatabaseUrl = None) -> None:
    """Show which schema revision the database is at, and the latest available."""
    url = settings_for(database_url).database_url
    typer.echo(f"database: {migrate.current_revision(url) or 'not created yet'}")
    typer.echo(f"latest:   {migrate.head_revision()}")


@app.command()
def seed(
    workspace: WorkspaceName = defaults.DEFAULT_WORKSPACE_NAME, database_url: DatabaseUrl = None
) -> None:
    """Create the default workspace, campaign and country policies. Safe to run again."""
    container = build_container(settings_for(database_url))
    result = seed_defaults(container.uow, workspace)
    typer.echo(
        f"workspace {workspace!r} ({'created' if result.workspace_created else 'already there'}), "
        f"campaign {'created' if result.campaign_created else 'already there'}, "
        f"{result.policies_created} country policies added"
    )


@app.command("import-legacy-xlsx")
def import_legacy(
    path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    workspace: WorkspaceName = defaults.DEFAULT_WORKSPACE_NAME,
    database_url: DatabaseUrl = None,
) -> None:
    """Import the old campaign workbook once; running it again changes nothing."""
    container = build_container(settings_for(database_url))
    workspace_id = workspace_id_or_exit(container, workspace)
    try:
        result = import_legacy_xlsx(container.uow, workspace_id, path)
    except LegacyWorkbookError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    typer.echo(
        f"read {result.read} rows: {result.imported} imported, "
        f"{result.merged} already there, {result.rejected} rejected"
    )
