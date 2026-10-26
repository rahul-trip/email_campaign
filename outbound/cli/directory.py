"""``outbound directory``: share what customers already verified with the lead directory."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

import typer

from outbound.bootstrap import build_container
from outbound.cli.common import DatabaseUrl, settings_for

directory_app = typer.Typer(no_args_is_help=True, help="The shared verified lead directory.")


def register(app: typer.Typer) -> None:
    app.add_typer(directory_app, name="directory")


@directory_app.command("backfill")
def backfill(
    since: Annotated[
        str, typer.Option(help="Share addresses verified on or after this date (YYYY-MM-DD).")
    ],
    apply: Annotated[bool, typer.Option(help="Write them. Without it, only count.")] = False,
    database_url: DatabaseUrl = None,
) -> None:
    """Load the verified addresses recorded since the alpha began. A dry run first; add --apply.

    The worker's next pass folds them into the directory.
    """
    try:
        start = datetime.fromisoformat(since).replace(tzinfo=UTC)
    except ValueError:
        typer.echo("give the date as YYYY-MM-DD", err=True)
        raise typer.Exit(2) from None
    container = build_container(settings_for(database_url))
    with container.platform() as platform:
        workspaces = platform.workspaces.all()
    total = 0
    for workspace in workspaces:
        with container.uow(workspace.id) as uow:
            total += uow.directory.backfill(start, dry_run=not apply)
            if apply:
                uow.commit()
    verb = "shared" if apply else "would be shared (add --apply to write them)"
    typer.echo(f"{total} address(es) {verb}, from {len(workspaces)} workspace(s)")
