"""``outbound targets``: add companies to work on, and settle the ones that need a human."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from outbound.bootstrap import Container, build_container
from outbound.cli.common import DatabaseUrl, WorkspaceName, settings_for, workspace_id_or_exit
from outbound.db.errors import NotFound
from outbound.domain.enums import ImportRowStatus, ImportSource
from outbound.domain.errors import InvalidInput
from outbound.pipeline import metered_search_or_none
from outbound.services import defaults
from outbound.services.intake import IntakeReport, IntakeService, load_rows

targets_app = typer.Typer(
    no_args_is_help=True, help="Add target companies and confirm unclear ones."
)

CampaignName = Annotated[str, typer.Option("--campaign", help="Campaign the companies belong to.")]
Personal = Annotated[
    bool, typer.Option("--allow-personal-domain", help="Keep free-mail addresses (gmail, ...).")
]


def _service(
    container: Container, workspace_id: str, *, allow_personal_domain: bool
) -> IntakeService:
    return IntakeService(
        container.uow,
        workspace_id,
        metered_search_or_none(container, workspace_id),
        allow_personal_domain=allow_personal_domain,
    )


def _campaign_id(container: Container, workspace_id: str, name: str) -> str:
    with container.uow(workspace_id) as uow:
        campaign = uow.campaigns.by_name(name)
    if campaign is None:
        typer.echo(f"no campaign named {name!r}: run `outbound seed` first", err=True)
        raise typer.Exit(1)
    return campaign.id


def _print(report: IntakeReport) -> None:
    for row in report.rows:
        where = f"row {row.row_number}" if row.row_number else "row"
        detail = f" - {row.reason}" if row.reason else ""
        typer.echo(f"{where}: {row.status.value} {row.domain or ''}{detail}".rstrip())
    counts = ", ".join(
        f"{report.count(status)} {status.value.replace('_', ' ')}"
        for status in ImportRowStatus
        if report.count(status)
    )
    typer.echo(f"read {report.read}: {counts or 'nothing'}")
    if report.validate_only:
        typer.echo("validate-only: nothing was saved")
    if report.count(ImportRowStatus.NEEDS_CONFIRMATION):
        typer.echo("settle waiting rows with: outbound targets confirm ROW_ID DOMAIN")


@targets_app.command("import")
def import_file(
    path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    validate_only: Annotated[
        bool, typer.Option("--validate-only", help="Check the file; save and search nothing.")
    ] = False,
    campaign: CampaignName = defaults.DEFAULT_CAMPAIGN_NAME,
    allow_personal_domain: Personal = False,
    workspace: WorkspaceName = defaults.DEFAULT_WORKSPACE_NAME,
    database_url: DatabaseUrl = None,
) -> None:
    """Import a CSV or XLSX file of targets."""
    container = build_container(settings_for(database_url))
    workspace_id = workspace_id_or_exit(container, workspace)
    try:
        rows = load_rows(path)
    except InvalidInput as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    report = _service(container, workspace_id, allow_personal_domain=allow_personal_domain).run(
        rows,
        source=ImportSource.XLSX if path.suffix.lower().startswith(".xls") else ImportSource.CSV,
        campaign_id=_campaign_id(container, workspace_id, campaign),
        filename=path.name,
        validate_only=validate_only,
    )
    _print(report)


@targets_app.command("add")
def add(
    company: Annotated[str | None, typer.Option("--company", help="Company name.")] = None,
    website: Annotated[str | None, typer.Option("--website", help="Website or domain.")] = None,
    email: Annotated[str | None, typer.Option("--email", help="A known work email.")] = None,
    person: Annotated[str | None, typer.Option("--person", help="A known decision-maker.")] = None,
    title: Annotated[str | None, typer.Option("--title")] = None,
    linkedin: Annotated[
        str | None, typer.Option("--linkedin", help="Profile URL (not fetched).")
    ] = None,
    country: Annotated[str | None, typer.Option("--country")] = None,
    note: Annotated[str | None, typer.Option("--note", help="Context for the copywriter.")] = None,
    priority: Annotated[int | None, typer.Option("--priority", min=1, max=9)] = None,
    validate_only: Annotated[bool, typer.Option("--validate-only")] = False,
    campaign: CampaignName = defaults.DEFAULT_CAMPAIGN_NAME,
    allow_personal_domain: Personal = False,
    workspace: WorkspaceName = defaults.DEFAULT_WORKSPACE_NAME,
    database_url: DatabaseUrl = None,
) -> None:
    """Add one target from the command line."""
    row = {
        key: value
        for key, value in {
            "company": company,
            "website": website,
            "email": email,
            "person": person,
            "title": title,
            "linkedin": linkedin,
            "country": country,
            "notes": note,
            "priority": priority,
        }.items()
        if value is not None
    }
    if not row:
        typer.echo("give at least one of --company, --website, --email or --linkedin", err=True)
        raise typer.Exit(1)
    container = build_container(settings_for(database_url))
    workspace_id = workspace_id_or_exit(container, workspace)
    report = _service(container, workspace_id, allow_personal_domain=allow_personal_domain).run(
        [row],
        source=ImportSource.CLI,
        campaign_id=_campaign_id(container, workspace_id, campaign),
        validate_only=validate_only,
    )
    _print(report)


@targets_app.command("pending")
def pending(
    workspace: WorkspaceName = defaults.DEFAULT_WORKSPACE_NAME, database_url: DatabaseUrl = None
) -> None:
    """List rows waiting for a decision about which website they mean."""
    container = build_container(settings_for(database_url))
    workspace_id = workspace_id_or_exit(container, workspace)
    rows = IntakeService(container.uow, workspace_id, None).needing_confirmation()
    for row in rows:
        guess = row.resolved_domain or "no guess"
        typer.echo(f"{row.id}  {guess}  {row.reason or ''}  {dict(row.raw)}")
    if not rows:
        typer.echo("nothing is waiting")


@targets_app.command("confirm")
def confirm(
    row_id: Annotated[str, typer.Argument(help="Row id from `targets pending`.")],
    domain: Annotated[str, typer.Argument(help="The company's real website or domain.")],
    workspace: WorkspaceName = defaults.DEFAULT_WORKSPACE_NAME,
    database_url: DatabaseUrl = None,
) -> None:
    """Say which website a waiting row means; the company is then created."""
    container = build_container(settings_for(database_url))
    workspace_id = workspace_id_or_exit(container, workspace)
    try:
        outcome = IntakeService(container.uow, workspace_id, None).confirm(row_id, domain)
    except (InvalidInput, NotFound) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    typer.echo(f"{outcome.status.value} {outcome.domain or ''} {outcome.reason or ''}".strip())
