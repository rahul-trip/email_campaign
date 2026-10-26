"""``outbound vendors``: move the platform's vendor keys and model settings into the database."""

from __future__ import annotations

import typer

from outbound.bootstrap import build_container
from outbound.cli.common import DatabaseUrl, settings_for
from outbound.services.vendors import VendorService

vendors_app = typer.Typer(no_args_is_help=True, help="Vendor API keys and model settings.")


def register(app: typer.Typer) -> None:
    app.add_typer(vendors_app, name="vendors")


@vendors_app.command("import-env")
def import_env(database_url: DatabaseUrl = None) -> None:
    """Copy the keys now in the environment into the database, once.

    A vendor that already has a key in the database is left alone. After this, the admin console
    manages the keys; Doppler keeps only the infrastructure secrets.
    """
    container = build_container(settings_for(database_url))
    copied = VendorService(container.platform, container.settings).import_env()
    typer.echo(f"copied: {', '.join(copied)}" if copied else "nothing to copy")
