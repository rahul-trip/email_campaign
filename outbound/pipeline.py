"""Assembles the working pipeline: real providers wrapped in the meter, stages, runner and tick.

This is the one place that knows which stage gets which provider. Tests call ``assemble`` with
fake providers; the CLI calls ``real_providers`` first. Every paid provider is wrapped in the
meter here, so a stage cannot be handed an unmetered one by mistake.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from outbound.bootstrap import Container
from outbound.config import Settings
from outbound.domain.entities import Workspace
from outbound.domain.enums import CompanySource, ImportRowStatus, ImportSource
from outbound.domain.errors import ConfigurationError
from outbound.providers.budget import BudgetPolicy
from outbound.providers.metered import (
    Meter,
    MeteredFinder,
    MeteredLlm,
    MeteredRegistry,
    MeteredResolver,
    MeteredSearch,
    MeteredVerifier,
)
from outbound.providers.ports import (
    CatchAllResolver,
    CompanyRegistry,
    EmailFinder,
    EmailVerifier,
    LlmClient,
    Mailbox,
    SearchProvider,
)
from outbound.providers.pricing import DEFAULT_LLM_PRICES, DEFAULT_PRICES
from outbound.providers.registry import (
    build_company_registry,
    build_finder_chain,
    build_llm,
    build_mailbox_if_configured,
    build_resolver,
    build_search,
    build_verifier,
)
from outbound.runner.guards import Guards
from outbound.runner.runner import Runner, RunReport
from outbound.runner.tick import Job, Tick
from outbound.services import defaults
from outbound.services.intake import IntakeService, discover_rows
from outbound.services.review import ReviewService
from outbound.services.runs import RunMode, RunRequest, RunService
from outbound.stages.base import Stage
from outbound.stages.contacts import ContactsStage
from outbound.stages.copy.stage import CopyStage
from outbound.stages.deliver import DeliverStage
from outbound.stages.email.poller import CatchAllPoller
from outbound.stages.email.stage import EmailDeps, EmailStage
from outbound.stages.gate import GateStage
from outbound.stages.research.graph import ResearchDeps
from outbound.stages.research.stage import ResearchStage
from outbound.stages.sync import SentSync


@dataclass(frozen=True)
class Providers:
    """The raw (unmetered) vendors. ``resolver`` and ``registry`` are optional."""

    search: SearchProvider
    llm: LlmClient
    finders: list[EmailFinder]
    verifier: EmailVerifier
    resolver: CatchAllResolver | None = None
    registry: CompanyRegistry | None = None
    mailbox: Mailbox | None = None


@dataclass(frozen=True)
class Pipeline:
    runner: Runner
    tick: Tick
    review: ReviewService
    runs: RunService
    intake: IntakeService
    meter: Meter
    search: SearchProvider
    stage_names: list[str] = field(default_factory=list)
    has_mailbox: bool = False


class NotConfigured(Exception):
    """A provider the pipeline needs has no credentials; the message names what to set."""


def real_providers(settings: Settings) -> Providers:
    from outbound.providers.errors import ProviderError

    try:
        resolver: CatchAllResolver | None = None
        try:
            resolver = build_resolver(settings)
        except ProviderError:
            resolver = None  # no resolver configured: catch-alls stay unverified
        mailbox = build_mailbox_if_configured(settings)
        return Providers(
            search=build_search(settings),
            llm=build_llm(settings),
            finders=build_finder_chain(settings),
            verifier=build_verifier(settings),
            resolver=resolver,
            registry=build_company_registry(settings),
            mailbox=mailbox,
        )
    except ProviderError as error:
        raise NotConfigured(str(error)) from None


def _workspace(container: Container, workspace_id: str) -> Workspace:
    with container.uow.admin() as admin:
        workspace = admin.workspaces.get(workspace_id)
    if workspace is None:
        raise ConfigurationError(f"workspace {workspace_id} does not exist")
    return workspace


def build_meter(container: Container, workspace_id: str) -> Meter:
    """The one way to get a meter: with the configured prices, monthly caps and the workspace's
    per-prospect ceiling, so no path to a paid vendor can skip a cap."""
    workspace = _workspace(container, workspace_id)
    settings = container.settings
    return Meter(
        container.uow,
        workspace_id,
        prices={**DEFAULT_PRICES, **settings.provider_prices},
        budget=BudgetPolicy.from_workspace_settings(
            workspace.settings, settings.monthly_caps_micro_usd
        ),
    )


def assemble(container: Container, workspace_id: str, providers: Providers) -> Pipeline:
    settings = container.settings
    uow = container.uow
    workspace = _workspace(container, workspace_id)
    budget = BudgetPolicy.from_workspace_settings(
        workspace.settings, settings.monthly_caps_micro_usd
    )
    meter = build_meter(container, workspace_id)
    llm_prices = {**DEFAULT_LLM_PRICES, **settings.llm_prices}
    search = MeteredSearch(providers.search, meter)
    llm = MeteredLlm(providers.llm, meter, prices=llm_prices)
    registry = MeteredRegistry(providers.registry, meter) if providers.registry else None
    finders = [MeteredFinder(f, meter) for f in providers.finders]
    verifier = MeteredVerifier(providers.verifier, meter)
    resolver = MeteredResolver(providers.resolver, meter) if providers.resolver else None

    stages: list[Stage] = [
        ResearchStage(ResearchDeps(search, llm, registry)),
        GateStage(),
        ContactsStage(),
        EmailStage(EmailDeps(finders, verifier, resolver)),
        CopyStage(llm),
    ]
    jobs: list[Job] = []
    if resolver is not None:
        jobs.append(CatchAllPoller(uow, workspace_id, resolver))
    if providers.mailbox is not None:
        stages.append(DeliverStage(providers.mailbox))
        jobs.append(SentSync(uow, workspace_id, providers.mailbox))

    runner = Runner(uow, workspace_id, stages, Guards(budget))
    return Pipeline(
        runner=runner,
        tick=Tick(uow, workspace_id, runner, jobs),
        review=ReviewService(uow, workspace_id),
        runs=RunService(uow, workspace_id),
        intake=IntakeService(uow, workspace_id, search),
        meter=meter,
        search=search,
        stage_names=[stage.name for stage in stages],
        has_mailbox=providers.mailbox is not None,
    )


def execute_run(
    pipeline: Pipeline,
    container: Container,
    workspace_id: str,
    request: RunRequest,
    *,
    run_id: str | None = None,
) -> RunReport:
    """Optionally look for new companies, then run the pipeline. Used by the CLI and the worker."""
    if request.mode is not RunMode.MANUAL:
        discover_companies(pipeline, container, workspace_id, request.campaign, request.discover)
    return pipeline.runner.run_pipeline(
        limit=request.limit, only=set(request.only) or None, run_id=run_id
    )


def discover_companies(
    pipeline: Pipeline, container: Container, workspace_id: str, campaign_name: str, count: int
) -> int:
    """Search the web for companies that fit the campaign and add them as discovered targets."""
    with container.uow(workspace_id) as uow:
        campaign = uow.campaigns.by_name(campaign_name)
    if campaign is None:
        raise LookupError(f"no campaign named {campaign_name!r}")
    query = campaign.icp_description or defaults.DEFAULT_ICP
    rows = discover_rows(pipeline.search, [query], per_query=count)
    report = pipeline.intake.run(
        rows,
        source=ImportSource.CLI,
        company_source=CompanySource.DISCOVERY,
        campaign_id=campaign.id,
    )
    return report.count(ImportRowStatus.ACCEPTED)


def metered_search_or_none(container: Container, workspace_id: str) -> SearchProvider | None:
    """Tavily behind the meter, or None when no key is set (name targets then wait for you)."""
    if not container.settings.tavily_api_key.get_secret_value():
        return None
    return MeteredSearch(build_search(container.settings), build_meter(container, workspace_id))
