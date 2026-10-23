"""The services a request works with, built for the request's workspace.

Vendor clients are built once per process (they hold no workspace); each request wraps them in
its own workspace's meters and services, which are cheap. Until Phase 6b the workspace is the
one configured for the deployment (``tenant``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends, Request

from outbound.bootstrap import Container
from outbound.providers.ports import LlmClient, Mailbox, SearchProvider
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
    writer: LlmClient | None = None,
    settings_service: SettingsService | None = None,
) -> Services:
    uow = container.uow
    intake = IntakeService(uow, workspace_id, search)
    return Services(
        container=container,
        workspace_id=workspace_id,
        intake=intake,
        review=ReviewService(uow, workspace_id, writer),
        leads=LeadService(uow, workspace_id),
        runs=RunService(uow, workspace_id),
        settings=settings_service or SettingsService(uow, workspace_id),
        reports=ReportService(uow, workspace_id),
        webhook=WebhookService(uow, workspace_id, intake),
        privacy=PrivacyService(uow, workspace_id, mailbox),
    )


class ServicesSource(Protocol):
    def for_tenant(self, workspace_id: str) -> Services: ...


@dataclass(frozen=True)
class ServicesFactory:
    """Builds a request's services: shared vendor clients, this workspace's meters."""

    container: Container
    search: SearchProvider | None = None  # raw; metered per workspace
    writer: LlmClient | None = None  # raw; metered per workspace
    mailbox: Mailbox | None = None

    def for_tenant(self, workspace_id: str) -> Services:
        from outbound.pipeline import meter_search, meter_writer

        container = self.container
        return build_services(
            container,
            workspace_id,
            search=meter_search(container, workspace_id, self.search) if self.search else None,
            mailbox=self.mailbox,
            writer=meter_writer(container, workspace_id, self.writer) if self.writer else None,
        )


@dataclass(frozen=True)
class FixedServices:
    """Services built in advance for one workspace (tests and scripts)."""

    services: Services

    def for_tenant(self, workspace_id: str) -> Services:
        if workspace_id != self.services.workspace_id:
            raise LookupError(f"no services for workspace {workspace_id}")
        return self.services


def tenant(request: Request) -> str:
    """The workspace this request acts in. Phase 6b replaces this with the signed-in user's
    membership; until then it is the deployment's configured workspace."""
    workspace_id: str = request.app.state.workspace_id
    return workspace_id


def services(request: Request, workspace_id: Annotated[str, Depends(tenant)]) -> Services:
    source: ServicesSource = request.app.state.services_source
    return source.for_tenant(workspace_id)
