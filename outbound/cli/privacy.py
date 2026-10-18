"""``outbound forget`` and ``outbound suppress``: honour erasure requests and opt-outs."""

from __future__ import annotations

from typing import Annotated

import typer

from outbound.bootstrap import build_container
from outbound.cli.common import DatabaseUrl, WorkspaceName, settings_for, workspace_id_or_exit
from outbound.db.errors import NotFound
from outbound.domain.errors import InvalidInput
from outbound.providers.registry import build_mailbox_if_configured
from outbound.services import defaults
from outbound.services.leads import LeadError
from outbound.services.privacy import PrivacyResult, PrivacyService


def _service(database_url: str | None, workspace: str) -> PrivacyService:
    container = build_container(settings_for(database_url))
    return PrivacyService(
        container.uow,
        workspace_id_or_exit(container, workspace),
        build_mailbox_if_configured(container.settings),
    )


def _report(result: PrivacyResult) -> None:
    typer.echo(f"{result.messages_cancelled} unsent email(s) cancelled")
    if result.drafts_deleted:
        typer.echo(f"{result.drafts_deleted} draft(s) deleted from the mailbox")
    for draft_id in result.drafts_left:
        typer.echo(f"DELETE BY HAND from your Drafts folder: {draft_id}", err=True)


def register(app: typer.Typer) -> None:
    @app.command()
    def forget(
        email: Annotated[str, typer.Argument(help="The address of the person to erase.")],
        yes: Annotated[bool, typer.Option("--yes", help="Do not ask first.")] = False,
        workspace: WorkspaceName = defaults.DEFAULT_WORKSPACE_NAME,
        database_url: DatabaseUrl = None,
    ) -> None:
        """Erase a person for good: suppress the address and remove what identifies them."""
        question = f"Erase everything identifying {email} and never contact them again?"
        if not yes and not typer.confirm(f"{question} This cannot be undone"):
            raise typer.Exit(1)
        result = _service(database_url, workspace).forget(email)
        typer.echo(
            "erased" if result.found else "we held nothing on that address; it is now suppressed"
        )
        _report(result)

    @app.command("delete-lead")
    def delete_lead(
        domain: Annotated[str, typer.Argument(help="The lead's website domain, as listed.")],
        suppress_domain: Annotated[
            bool, typer.Option("--suppress", help="Also never contact this domain again.")
        ] = False,
        yes: Annotated[bool, typer.Option("--yes", help="Do not ask first.")] = False,
        workspace: WorkspaceName = defaults.DEFAULT_WORKSPACE_NAME,
        database_url: DatabaseUrl = None,
    ) -> None:
        """Permanently delete a lead and its people, emails and history."""
        container = build_container(settings_for(database_url))
        workspace_id = workspace_id_or_exit(container, workspace)
        with container.uow(workspace_id) as uow:
            company = uow.companies.by_domain(domain.strip().lower())
        if company is None:
            typer.echo(f"no lead with the domain {domain!r}", err=True)
            raise typer.Exit(1)
        if not yes:
            typed = typer.prompt(
                f"This permanently deletes {company.domain}. Type its domain to confirm"
            )
            if typed.strip().lower() != company.domain:
                typer.echo("not the same: nothing was deleted", err=True)
                raise typer.Exit(1)
        service = PrivacyService(
            container.uow, workspace_id, build_mailbox_if_configured(container.settings)
        )
        try:
            result = service.delete_lead(
                company.id, confirm_domain=company.domain, also_suppress_domain=suppress_domain
            )
        except (InvalidInput, LeadError) as error:
            typer.echo(str(error), err=True)
            raise typer.Exit(1) from error
        typer.echo(
            f"deleted {result.domain}: {result.contacts_removed} person(s), "
            f"{result.messages_removed} email(s)"
        )
        if result.domain_suppressed:
            typer.echo("the domain is on the do-not-contact list")
        if result.drafts_deleted:
            typer.echo(f"{result.drafts_deleted} draft(s) deleted from the mailbox")
        for draft_id in result.drafts_left:
            typer.echo(f"DELETE BY HAND from your Drafts folder: {draft_id}", err=True)

    @app.command()
    def suppress(
        value: Annotated[str, typer.Argument(help="An email address or a domain.")],
        workspace: WorkspaceName = defaults.DEFAULT_WORKSPACE_NAME,
        database_url: DatabaseUrl = None,
    ) -> None:
        """Never contact an address or a whole domain again (an opt-out)."""
        try:
            result = _service(database_url, workspace).suppress_value(value)
        except (InvalidInput, NotFound) as error:
            typer.echo(str(error), err=True)
            raise typer.Exit(1) from error
        typer.echo("suppressed" if result.found else "suppressed (we held nothing on it yet)")
        _report(result)
