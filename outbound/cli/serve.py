"""``outbound serve`` (the web app and API), ``outbound worker`` and ``outbound auth``."""

from __future__ import annotations

from typing import Annotated

import typer

from outbound.bootstrap import Container, build_container
from outbound.cli.common import DatabaseUrl, WorkspaceName, settings_for, workspace_id_or_exit
from outbound.db.isolation import isolation_problems
from outbound.domain.errors import ConfigurationError
from outbound.logging import get_logger
from outbound.services import defaults

log = get_logger(__name__)


def refuse_unsafe_database(container: Container) -> None:
    """Stop before serving if this connection could see other workspaces' rows (Phase 6a).

    In production that is fatal; elsewhere (a developer's Postgres) it is only logged.
    """
    problems = isolation_problems(container.engine)
    if not problems:
        return
    production = container.settings.environment == "production"
    for problem in problems:
        log.error("tenant_isolation_unsafe", problem=problem, refused=production)
    if production:
        typer.echo("Refusing to start: " + "; ".join(problems), err=True)
        raise typer.Exit(1)


auth_app = typer.Typer(no_args_is_help=True, help="Operator login.")
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


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
        refuse_unsafe_database(container)
        config = container.settings
        bind_host = host or config.api_host
        if bind_host not in LOOPBACK and not config.cookie_secure:
            typer.echo(
                f"Refusing to listen on {bind_host}: the login cookie would travel unencrypted. "
                "Serve it behind https and set COOKIE_SECURE=true, or use 127.0.0.1.",
                err=True,
            )
            raise typer.Exit(1)
        try:
            api = create_app_from_container(container)
        except ConfigurationError as error:
            typer.echo(str(error), err=True)
            raise typer.Exit(1) from error
        log.info(
            "service_started",
            role="api",
            host=bind_host,
            port=port or config.api_port,
            database=container.engine.url.render_as_string(hide_password=True),
            log_level=config.log_level,
        )
        # log_config=None keeps our logging setup; the access line is replaced by the middleware.
        uvicorn.run(
            api,
            host=bind_host,
            port=port or config.api_port,
            log_config=None,
            access_log=False,
            proxy_headers=True,
            forwarded_allow_ips=config.forwarded_allow_ips,
        )

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
        refuse_unsafe_database(container)
        workspace_id = workspace_id_or_exit(container, workspace)
        try:
            pipeline = assemble(container, workspace_id, real_providers(container.settings))
        except NotConfigured as error:
            typer.echo(f"not configured: {error}", err=True)
            raise typer.Exit(1) from error
        log.info(
            "service_started",
            role="worker",
            workspace_id=workspace_id,
            poll_seconds=poll_seconds,
            database=container.engine.url.render_as_string(hide_password=True),
        )
        typer.echo("worker ready; waiting for queued runs (Ctrl-C to stop)")
        try:
            Worker(container, workspace_id, pipeline).run_forever(poll_seconds=poll_seconds)
        except KeyboardInterrupt:
            typer.echo("stopped")
