"""Pieces every command group shares: the database option, the settings and the workspace."""

from __future__ import annotations

from typing import Annotated

import typer

from outbound.bootstrap import Container
from outbound.config import Settings
from outbound.domain.errors import ConfigurationError
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
    try:
        return container.workspace_id(name)
    except ConfigurationError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
