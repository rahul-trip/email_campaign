"""``outbound secrets``: the keys that encrypt workspaces' mailbox tokens and passwords."""

from __future__ import annotations

import typer

from outbound.bootstrap import build_container
from outbound.cli.common import DatabaseUrl, settings_for
from outbound.db.crypto import new_key

secrets_app = typer.Typer(no_args_is_help=True, help="Encryption keys for stored secrets.")


def register(app: typer.Typer) -> None:
    app.add_typer(secrets_app, name="secrets")


@secrets_app.command("new-key")
def new_key_command() -> None:
    """Print a fresh key. Add it to SECRETS_KEYS under a higher version, then run rotate."""
    typer.echo(new_key())


@secrets_app.command("rotate")
def rotate(database_url: DatabaseUrl = None) -> None:
    """Encrypt every stored secret again with the newest key in SECRETS_KEYS.

    Afterwards the older keys can be removed from SECRETS_KEYS.
    """
    container = build_container(settings_for(database_url))
    with container.platform() as platform:
        workspaces = platform.workspaces.all()
    total = 0
    for workspace in workspaces:
        with container.uow(workspace.id) as uow:
            total += uow.credentials.reseal_all()
            uow.commit()
    typer.echo(f"{total} secret(s) re-encrypted across {len(workspaces)} workspace(s)")
