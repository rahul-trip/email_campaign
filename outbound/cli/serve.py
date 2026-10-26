"""``outbound serve`` (the web app and API), ``outbound worker`` and ``outbound users``."""

from __future__ import annotations

from typing import Annotated

import typer

from outbound.bootstrap import Container, build_container
from outbound.cli.common import DatabaseUrl, settings_for
from outbound.db.isolation import isolation_problems
from outbound.domain.enums import MembershipRole, PlatformRole
from outbound.domain.errors import ConfigurationError
from outbound.logging import get_logger

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


users_app = typer.Typer(no_args_is_help=True, help="People who sign in to the web app.")
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def register(app: typer.Typer) -> None:
    app.add_typer(users_app, name="users")

    @users_app.command("create")
    def create_user(
        email: Annotated[str, typer.Option(help="The address they sign in with.")],
        password: Annotated[
            str, typer.Option(prompt=True, hide_input=True, confirmation_prompt=True)
        ],
        name: Annotated[str, typer.Option()] = "",
        workspace: Annotated[
            str | None, typer.Option(help="Slug of a workspace to add them to.")
        ] = None,
        role: Annotated[MembershipRole, typer.Option(help="Their role there.")] = (
            MembershipRole.ADMIN
        ),
        platform_role: Annotated[
            PlatformRole | None, typer.Option(help="Make them platform staff.")
        ] = None,
        database_url: DatabaseUrl = None,
    ) -> None:
        """Create an account directly, without an invitation (the first admin, staff)."""
        from outbound.providers.adapters.transactional_email import LogEmail
        from outbound.services.identity import IdentityError, IdentityService

        container = build_container(settings_for(database_url))
        workspace_id = None
        if workspace:
            with container.platform() as platform:
                found = platform.workspaces.by_slug(workspace)
            if found is None:
                typer.echo(f"no workspace with slug {workspace!r}", err=True)
                raise typer.Exit(1)
            workspace_id = found.id
        config = container.settings
        ids = IdentityService(
            container.identity, container.platform, container.uow, LogEmail(),
            base_url=config.app_base_url, terms_version=config.terms_version,
        )  # fmt: skip
        try:
            user = ids.add_user(
                email, password, name=name, platform_role=platform_role,
                workspace_id=workspace_id, role=role,
            )  # fmt: skip
        except IdentityError as error:
            typer.echo(error.detail, err=True)
            raise typer.Exit(1) from None
        typer.echo(f"user {user.id} ({user.email}) ready")

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
                f"Refusing to listen on {bind_host}: the session cookie would travel unencrypted. "
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
        threads: Annotated[int, typer.Option(help="Workspaces worked on at the same time.")] = 4,
        tick_minutes: Annotated[
            float, typer.Option(help="Retries, mailbox sync and due leads, this often (0: never).")
        ] = 15,
        database_url: DatabaseUrl = None,
    ) -> None:
        """Execute queued runs and the periodic tick for every workspace, until stopped."""
        from datetime import timedelta

        from outbound.pipeline import NotConfigured, assemble, real_providers
        from outbound.worker import Worker

        container = build_container(settings_for(database_url))
        refuse_unsafe_database(container)
        from outbound.services.vendors import LiveProviders, VendorService

        # Rebuilt whenever an admin changes a key or a model setting, without a restart.
        live = LiveProviders(VendorService(container.platform, container.settings), real_providers)
        try:
            live.get()
        except NotConfigured as error:
            typer.echo(f"not configured: {error}", err=True)
            raise typer.Exit(1) from error
        log.info(
            "service_started",
            role="worker",
            threads=threads,
            tick_minutes=tick_minutes,
            poll_seconds=poll_seconds,
            database=container.engine.url.render_as_string(hide_password=True),
        )
        typer.echo("worker ready; waiting for queued runs (Ctrl-C to stop)")
        tick_every = timedelta(minutes=tick_minutes) if tick_minutes > 0 else None
        engine = Worker(
            container,
            lambda workspace_id: assemble(container, workspace_id, live.get()),
            threads=threads,
            tick_every=tick_every,
        )
        try:
            engine.run_forever(poll_seconds=poll_seconds)
        except KeyboardInterrupt:
            typer.echo("stopped")
