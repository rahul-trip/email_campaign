"""Everyday commands: run the pipeline, tick, review, retry, status and reports."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Annotated

import typer

from outbound.bootstrap import Container, build_container
from outbound.cli.common import DatabaseUrl, WorkspaceName, settings_for, workspace_id_or_exit
from outbound.db.types import utcnow
from outbound.domain.enums import (
    CompanyStatus,
    HoldReason,
)
from outbound.domain.money import format_usd
from outbound.pipeline import NotConfigured, Pipeline, assemble, execute_run, real_providers
from outbound.runner.runner import RunReport
from outbound.runner.tick import TickReport
from outbound.services import defaults
from outbound.services.reports import ReportService
from outbound.services.review import ReviewError, ReviewService
from outbound.services.runs import RunMode, RunRequest

review_app = typer.Typer(
    no_args_is_help=True, help="Read, edit, approve or reject generated emails."
)
report_app = typer.Typer(no_args_is_help=True, help="Quality and cost reports.")

LONG_AGO = timedelta(days=3650)


def _pipeline(container: Container, workspace_id: str) -> Pipeline:
    try:
        return assemble(container, workspace_id, real_providers(container.settings))
    except NotConfigured as error:
        typer.echo(f"not configured: {error}", err=True)
        raise typer.Exit(1) from error


def _review(database_url: str | None, workspace: str) -> ReviewService:
    container = build_container(settings_for(database_url))
    return ReviewService(container.uow, workspace_id_or_exit(container, workspace))


def _guard[T](action: Callable[[], T]) -> T:
    try:
        return action()
    except ReviewError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error


def _print_run(report: RunReport) -> None:
    for stage, counts in report.counts.items():
        summary = ", ".join(f"{n} {name}" for name, n in sorted(counts.items())) or "nothing due"
        typer.echo(f"{stage:<9} {summary}")
    cost = format_usd(report.cost_micro_usd)
    typer.echo(f"run {report.run_id[:8]} {report.status.value}, cost {cost}")


def _print_tick(report: TickReport) -> None:
    typer.echo(f"retried {report.retried}")
    for name, counts in report.jobs.items():
        typer.echo(f"{name}: " + ", ".join(f"{n} {k}" for k, n in counts.items()))
    if report.pipeline:
        _print_run(report.pipeline)


def register(app: typer.Typer) -> None:
    app.add_typer(review_app, name="review")
    app.add_typer(report_app, name="report")

    @app.command()
    def run(
        limit: Annotated[int, typer.Option(help="Most leads taken by each stage.")] = 50,
        only: Annotated[str | None, typer.Option(help="Comma-separated stage names.")] = None,
        mode: Annotated[RunMode, typer.Option(help="manual, discovery or mixed.")] = RunMode.MANUAL,
        discover: Annotated[int, typer.Option(help="Companies to look for in discovery.")] = 10,
        campaign: Annotated[str, typer.Option()] = defaults.DEFAULT_CAMPAIGN_NAME,
        workspace: WorkspaceName = defaults.DEFAULT_WORKSPACE_NAME,
        database_url: DatabaseUrl = None,
    ) -> None:
        """Run every stage over the work that is due."""
        container = build_container(settings_for(database_url))
        workspace_id = workspace_id_or_exit(container, workspace)
        pipeline = _pipeline(container, workspace_id)
        request = RunRequest(
            limit=limit,
            only=tuple(part.strip() for part in only.split(",")) if only else (),
            mode=mode,
            discover=discover,
            campaign=campaign,
        )
        try:
            report = execute_run(pipeline, container, workspace_id, request)
        except LookupError as error:
            typer.echo(str(error), err=True)
            raise typer.Exit(1) from error
        _print_run(report)
        if not pipeline.has_mailbox:
            typer.echo("note: no mailbox is configured, so approved emails are not drafted")

    @app.command()
    def tick(
        limit: Annotated[int, typer.Option()] = 50,
        workspace: WorkspaceName = defaults.DEFAULT_WORKSPACE_NAME,
        database_url: DatabaseUrl = None,
    ) -> None:
        """One scheduler pass: retries, catch-all answers, the Sent sync, then the pipeline."""
        container = build_container(settings_for(database_url))
        pipeline = _pipeline(container, workspace_id_or_exit(container, workspace))
        _print_tick(pipeline.tick.run(limit=limit))

    @app.command()
    def retry(
        limit: Annotated[int, typer.Option()] = 50,
        workspace: WorkspaceName = defaults.DEFAULT_WORKSPACE_NAME,
        database_url: DatabaseUrl = None,
    ) -> None:
        """Send failed leads back to the stage that failed, once their wait is over."""
        container = build_container(settings_for(database_url))
        pipeline = _pipeline(container, workspace_id_or_exit(container, workspace))
        typer.echo(f"{pipeline.runner.retry_failed(limit=limit)} lead(s) sent back")

    @app.command()
    def status(
        workspace: WorkspaceName = defaults.DEFAULT_WORKSPACE_NAME, database_url: DatabaseUrl = None
    ) -> None:
        """Where every lead is, what is held and why, and what failed."""
        container = build_container(settings_for(database_url))
        workspace_id = workspace_id_or_exit(container, workspace)
        report = ReportService(container.uow, workspace_id).status()
        with container.uow(workspace_id) as uow:
            failed = uow.companies.due(CompanyStatus.FAILED, 20, utcnow() + LONG_AGO)
        counts, held, waiting = report.by_status, report.held, report.waiting_for_review
        for company_status in CompanyStatus:
            if counts.get(company_status):
                typer.echo(f"{company_status.value:<14}{counts[company_status]}")
        for reason, count in sorted(held.items()):
            typer.echo(f"  held for {reason.value}: {count}")
        for company in failed:
            typer.echo(f"  failed {company.domain} at {company.failed_stage}: {company.last_error}")
        typer.echo(
            f"{waiting} email(s) waiting for review" if waiting else "none waiting for review"
        )

    # ------------------------------------------------------------------ review

    @review_app.command("list")
    def review_list(
        workspace: WorkspaceName = defaults.DEFAULT_WORKSPACE_NAME, database_url: DatabaseUrl = None
    ) -> None:
        """The emails waiting for a decision."""
        items = _review(database_url, workspace).queue()
        for item in items:
            flag = "  FLAGGED" if item.flagged else ""
            typer.echo(
                f"{item.message.id[:8]}  {item.company.name or item.company.domain}"
                f" -> {item.contact.full_name} <{item.address.email}>{flag}"
            )
        if not items:
            typer.echo("nothing is waiting for review")

    @review_app.command("show")
    def review_show(
        ref: Annotated[str, typer.Argument(help="Message id, or the start of one.")],
        workspace: WorkspaceName = defaults.DEFAULT_WORKSPACE_NAME,
        database_url: DatabaseUrl = None,
    ) -> None:
        """One email next to what we know about the lead."""
        service = _review(database_url, workspace)
        detail = _guard(lambda: service.show(service.resolve(ref)))
        item = detail.item
        who = f"{item.contact.full_name} <{item.address.email}> ({item.contact.title})"
        typer.echo(f"To:      {who}")
        typer.echo(
            f"Company: {item.company.name or item.company.domain} [{item.company.country_code}]"
        )
        typer.echo(f"Fit:     {item.company.fit_score} - {item.company.fit_reason}")
        typer.echo(f"Subject: {item.message.subject}\n\n{item.message.generated_body}\n")
        report = item.message.lint_report or {}
        typer.echo(f"Words {report.get('word_count')}, reading grade {report.get('reading_grade')}")
        for issue in report.get("issues", []):
            typer.echo(f"  ! {issue['rule']}: {issue['message']}")
        research = item.company.research or {}
        typer.echo(f"\nResearch: {research.get('summary', '')}")
        for hook in research.get("hooks", []):
            typer.echo(f"  hook: {hook}")
        for note in detail.notes:
            typer.echo(f"  note: {note}")

    @review_app.command("approve")
    def review_approve(
        ref: Annotated[str, typer.Argument()],
        edit: Annotated[
            Path | None,
            typer.Option(
                "--edit", exists=True, dir_okay=False, help="File with your edited email."
            ),
        ] = None,
        workspace: WorkspaceName = defaults.DEFAULT_WORKSPACE_NAME,
        database_url: DatabaseUrl = None,
    ) -> None:
        """Approve an email, optionally with your edited version of the whole text."""
        service = _review(database_url, workspace)
        body = edit.read_text() if edit else None
        message = _guard(lambda: service.approve(service.resolve(ref), edited_body=body))
        suffix = " with your edit" if message.final_body is not None else ""
        typer.echo(f"approved{suffix}: {message.id[:8]}")

    @review_app.command("reject")
    def review_reject(
        ref: Annotated[str, typer.Argument()],
        reason: Annotated[str, typer.Option("--reason", help="Why; it is kept with the lead.")],
        workspace: WorkspaceName = defaults.DEFAULT_WORKSPACE_NAME,
        database_url: DatabaseUrl = None,
    ) -> None:
        """Reject an email and end work on the lead."""
        service = _review(database_url, workspace)
        message = _guard(lambda: service.reject(service.resolve(ref), reason))
        typer.echo(f"rejected: {message.id[:8]}")

    # ------------------------------------------------------------------ reports

    @report_app.command("quality")
    def report_quality(
        workspace: WorkspaceName = defaults.DEFAULT_WORKSPACE_NAME, database_url: DatabaseUrl = None
    ) -> None:
        """Share of sent first emails that went out unedited, lint flags and holds."""
        container = build_container(settings_for(database_url))
        report = ReportService(container.uow, workspace_id_or_exit(container, workspace)).quality()
        share = report.unedited_share
        shown = f" ({share:.0%}; target 80%)" if share is not None else " (nothing sent yet)"
        typer.echo(f"sent {report.sent}, unedited {report.unedited}{shown}")
        rate = report.flag_rate
        flagged = f" ({rate:.0%})" if rate is not None else ""
        typer.echo(f"written {report.written}, flagged by the linter {report.flagged}{flagged}")
        typer.echo(f"companies {report.companies}")
        for reason in HoldReason:
            if report.holds.get(reason):
                share_held = report.held_share(reason) or 0.0
                typer.echo(f"  held for {reason.value}: {report.holds[reason]} ({share_held:.0%})")
        if report.catch_all_share:
            typer.echo(f"  catch-all held share: {report.catch_all_share:.0%}")

    @report_app.command("cost")
    def report_cost(
        days: Annotated[int, typer.Option(help="Look back this many days.")] = 30,
        workspace: WorkspaceName = defaults.DEFAULT_WORKSPACE_NAME,
        database_url: DatabaseUrl = None,
    ) -> None:
        """Spend per provider and per prospect, and how many paid calls were made."""
        container = build_container(settings_for(database_url))
        now = utcnow()
        report = ReportService(container.uow, workspace_id_or_exit(container, workspace)).cost(
            now - timedelta(days=days), now + timedelta(seconds=1)
        )
        for provider, cost in report.by_provider.items():
            calls = report.calls_by_provider[provider]
            typer.echo(f"{provider:<18}{format_usd(cost):>10}  {calls} call(s)")
        typer.echo(f"total {format_usd(report.total)} over {days} day(s)")
        if report.per_prospect is not None:
            typer.echo(f"per prospect {format_usd(report.per_prospect)} across {report.prospects}")
        outcomes = ", ".join(f"{n} {o.value}" for o, n in sorted(report.outcomes.items()))
        typer.echo(f"calls: {outcomes or 'none'}; paid calls {report.paid_calls}")
