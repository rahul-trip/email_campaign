"""``outbound serve`` (the web app and API), ``outbound worker`` and ``outbound auth``."""

from __future__ import annotations

from typing import Annotated

import typer

from outbound.bootstrap import build_container
from outbound.cli.common import DatabaseUrl, WorkspaceName, settings_for, workspace_id_or_exit
from outbound.services import defaults

auth_app = typer.Typer(no_args_is_help=True, help="Operator login.")


def register(app: typer.Typer) -> None:
    app.add_typer(auth_app, name="auth")

    @auth_app.command("hash-password")
    def hash_password_command(
        password: Annotated[
            str, typer.Option(prompt=True, hide_input=True, confirmation_prompt=True)
        ],
    ) -> None:
        """Print the value to put in OPERATOR_PASSWORD_HASH."""
        from outbound.api.auth import hash_password

        typer.echo(hash_password(password))

    @app.command()
    def serve(
        host: Annotated[str | None, typer.Option(help="Defaults to API_HOST (127.0.0.1).")] = None,
        port: Annotated[int | None, typer.Option(help="Defaults to API_PORT (8000).")] = None,
        database_url: DatabaseUrl = None,
    ) -> None:
        """Serve the web app and API. Also run `outbound worker` so queued runs execute."""
        import uvicorn

        from outbound.api.app import create_app_from_container

        container = build_container(settings_for(database_url))
        try:
            api = create_app_from_container(container)
        except RuntimeError as error:
            typer.echo(str(error), err=True)
            raise typer.Exit(1) from error
        config = container.settings
        uvicorn.run(api, host=host or config.api_host, port=port or config.api_port)

    @app.command()
    def worker(
        poll_seconds: Annotated[float, typer.Option(help="Wait between checks when idle.")] = 2.0,
        workspace: WorkspaceName = defaults.DEFAULT_WORKSPACE_NAME,
        database_url: DatabaseUrl = None,
    ) -> None:
        """Execute runs queued from the web app, one after another, until stopped."""
        from outbound.pipeline import NotConfigured, assemble, real_providers
        from outbound.worker import Worker

        container = build_container(settings_for(database_url))
        workspace_id = workspace_id_or_exit(container, workspace)
        try:
            pipeline = assemble(container, workspace_id, real_providers(container.settings))
        except NotConfigured as error:
            typer.echo(f"not configured: {error}", err=True)
            raise typer.Exit(1) from error
        typer.echo("worker ready; waiting for queued runs (Ctrl-C to stop)")
        try:
            Worker(container, workspace_id, pipeline).run_forever(poll_seconds=poll_seconds)
        except KeyboardInterrupt:
            typer.echo("stopped")
