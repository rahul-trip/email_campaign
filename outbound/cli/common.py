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
    settings = Settings()
    # The option also reads DATABASE_URL, which Settings already has: only a different address given
    # on purpose replaces all three, so migrations keep running as the owner (MIGRATE_DATABASE_URL).
    if database_url and database_url != settings.database_url:
        settings = settings.model_copy(
            update={
                "database_url": database_url,
                "platform_database_url": database_url,
                "migrate_database_url": database_url,
            }
        )
    configure_logging(settings.log_level, settings.log_format, settings.environment)
    return settings


def workspace_id_or_exit(container: Container, name: str) -> str:
    try:
        return container.workspace_id(name)
    except ConfigurationError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error


def as_owner(settings: Settings) -> Settings:
    """The same settings connected as the tables' owner: migrations and seeding only."""
    owner = settings.migrate_database_url
    return settings.model_copy(update={"database_url": owner, "platform_database_url": owner})
