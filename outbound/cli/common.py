"""Pieces every command group shares: the database option, the settings and the workspace."""

from __future__ import annotations

from typing import Annotated

import typer

from outbound.bootstrap import Container
from outbound.config import Settings
from outbound.logging import configure_logging

DatabaseUrl = Annotated[
    str | None,
    typer.Option(
        "--database-url", envvar="DATABASE_URL", help="Defaults to DATABASE_URL or outbound.db."
    ),
]
WorkspaceName = Annotated[
    str, typer.Option("--workspace", help="Workspace name; created by `seed` if missing.")
]


def settings_for(database_url: str | None) -> Settings:
    configure_logging()
    settings = Settings()
    if database_url:
        settings = settings.model_copy(update={"database_url": database_url})
    return settings


def workspace_id_or_exit(container: Container, name: str) -> str:
    with container.uow.admin() as admin:
        found = admin.workspaces.by_name(name)
    if found is None:
        typer.echo(f"no workspace named {name!r}: run `outbound seed` first", err=True)
        raise typer.Exit(1)
    return found.id
