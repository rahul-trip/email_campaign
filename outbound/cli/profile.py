"""``outbound sender-profile``: see and confirm the facts every email is built from."""

from __future__ import annotations

from typing import Annotated

import typer

from outbound.bootstrap import build_container
from outbound.cli.common import DatabaseUrl, WorkspaceName, settings_for, workspace_id_or_exit
from outbound.services import defaults
from outbound.services.settings import REVIEWED_KEY, SettingsService

profile_app = typer.Typer(no_args_is_help=True, help="The sender profile behind every email.")


def _show(profile: dict[str, object]) -> None:
    for key, value in profile.items():
        if key in {REVIEWED_KEY, "narrative"}:
            continue
        shown = "\n    ".join(map(str, value)) if isinstance(value, list) else str(value or "")
        typer.echo(f"{key}: {shown or '(empty)'}")
    typer.echo(f"\nabout you:\n{profile.get('narrative') or '(empty)'}")
    typer.echo(f"\nreviewed: {profile.get(REVIEWED_KEY) or 'NO - emails will not be written'}")


def register(app: typer.Typer) -> None:
    app.add_typer(profile_app, name="sender-profile")

    @profile_app.command("show")
    def show(
        workspace: WorkspaceName = defaults.DEFAULT_WORKSPACE_NAME, database_url: DatabaseUrl = None
    ) -> None:
        """Print the profile and whether it has been reviewed."""
        container = build_container(settings_for(database_url))
        service = SettingsService(container.uow, workspace_id_or_exit(container, workspace))
        _show(service.sender_profile())

    @profile_app.command("review")
    def review(
        yes: Annotated[bool, typer.Option("--yes", help="Confirm without asking.")] = False,
        workspace: WorkspaceName = defaults.DEFAULT_WORKSPACE_NAME,
        database_url: DatabaseUrl = None,
    ) -> None:
        """Confirm that every statement in the profile is true, so emails may be written."""
        container = build_container(settings_for(database_url))
        service = SettingsService(container.uow, workspace_id_or_exit(container, workspace))
        _show(service.sender_profile())
        if not yes and not typer.confirm("\nIs every statement above true?"):
            typer.echo("Not confirmed. Edit the profile in Settings, then run this again.")
            raise typer.Exit(1)
        service.update_sender_profile({})
        typer.echo("Profile reviewed.")
