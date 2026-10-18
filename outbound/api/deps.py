"""The services one API process shares, built once at start-up."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from outbound.bootstrap import Container
from outbound.providers.ports import Mailbox, SearchProvider
from outbound.services.intake import IntakeService
from outbound.services.leads import LeadService
from outbound.services.privacy import PrivacyService
from outbound.services.reports import ReportService
from outbound.services.review import ReviewService
from outbound.services.runs import RunService
from outbound.services.settings import SettingsService
from outbound.services.webhook import WebhookService


@dataclass(frozen=True)
class Services:
    container: Container
    workspace_id: str
    intake: IntakeService
    review: ReviewService
    leads: LeadService
    runs: RunService
    settings: SettingsService
    reports: ReportService
    webhook: WebhookService
    privacy: PrivacyService


def build_services(
    container: Container,
    workspace_id: str,
    *,
    search: SearchProvider | None = None,
    mailbox: Mailbox | None = None,
    settings_service: SettingsService | None = None,
) -> Services:
    uow = container.uow
    intake = IntakeService(uow, workspace_id, search)
    return Services(
        container=container,
        workspace_id=workspace_id,
        intake=intake,
        review=ReviewService(uow, workspace_id),
        leads=LeadService(uow, workspace_id),
        runs=RunService(uow, workspace_id),
        settings=settings_service or SettingsService(uow, workspace_id),
        reports=ReportService(uow, workspace_id),
        webhook=WebhookService(uow, workspace_id, intake),
        privacy=PrivacyService(uow, workspace_id, mailbox),
    )


def services(request: Request) -> Services:
    result: Services = request.app.state.services
    return result
