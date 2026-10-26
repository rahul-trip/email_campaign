"""Assembles the working pipeline: real providers wrapped in the meter, stages, runner and tick.

This is the one place that knows which stage gets which provider. Tests call ``assemble`` with
fake providers; the CLI calls ``real_providers`` first. Every paid provider is wrapped in the
meter here, so a stage cannot be handed an unmetered one by mistake.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from outbound.bootstrap import Container
from outbound.config import Settings
from outbound.db.types import utcnow
from outbound.domain.entities import Workspace
from outbound.domain.enums import CompanySource, ImportRowStatus, ImportSource, UsageStep
from outbound.domain.errors import ConfigurationError
from outbound.logging import get_logger
from outbound.metering.budget import BudgetPolicy
from outbound.metering.metered import (
    Meter,
    MeteredFinder,
    MeteredLlm,
    MeteredRegistry,
    MeteredResolver,
    MeteredSearch,
    MeteredVerifier,
)
from outbound.metering.quota import quota_in
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
    build_oauth_apps,
    build_resolver,
    build_search,
    build_verifier,
)
from outbound.runner.guards import Guards
from outbound.runner.runner import Runner, RunReport
from outbound.runner.tick import Job, Tick
from outbound.services.inbox import InboxSync
from outbound.services.intake import IntakeService, discover_candidates, discovery_query
from outbound.services.privacy import PrivacyService
from outbound.services.resume import ResumeService
from outbound.services.review import ReviewService
from outbound.services.runs import RunMode, RunRequest, RunService
from outbound.stages.base import Stage
from outbound.stages.contacts import ContactsStage
from outbound.stages.copy.stage import CopyStage
from outbound.stages.deliver import DeliverStage
from outbound.stages.email.directory import DirectoryFinder
from outbound.stages.email.poller import CatchAllPoller
from outbound.stages.email.stage import EmailDeps, EmailStage
from outbound.stages.gate import GateStage
from outbound.stages.mailboxes import Mailboxes, MailboxHealth, StoredMailboxes, one
from outbound.stages.research.graph import ResearchDeps
from outbound.stages.research.stage import ResearchStage
from outbound.stages.sync import SentSync

log = get_logger(__name__)


@dataclass(frozen=True)
class Providers:
    """The raw (unmetered) vendors. ``resolver`` and ``registry`` are optional."""

    search: SearchProvider
    llm: LlmClient
    finders: list[EmailFinder]
    verifier: EmailVerifier
    resolver: CatchAllResolver | None = None
    registry: CompanyRegistry | None = None
    # One mailbox for every workspace (tests, scripts). Real runs leave it out: each workspace
    # uses the mailboxes it connected (``StoredMailboxes``).
    mailbox: Mailbox | None = None
    copy_llm: LlmClient | None = None  # the writer's model; None means ``llm``


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
        return Providers(
            search=build_search(settings),
            llm=build_llm(settings),
            finders=build_finder_chain(settings),
            verifier=build_verifier(settings),
            resolver=resolver,
            registry=build_company_registry(settings),
            copy_llm=build_llm(settings, model=settings.llm_copy_model)
            if settings.llm_copy_model
            else None,
        )
    except ProviderError as error:
        raise NotConfigured(str(error)) from None


def _workspace(container: Container, workspace_id: str) -> Workspace:
    with container.uow(workspace_id) as uow:
        workspace = uow.workspace()
    if workspace is None:
        raise ConfigurationError(f"workspace {workspace_id} does not exist")
    return workspace


def build_meter(container: Container, workspace_id: str) -> Meter:
    """The one way to get a meter: with the configured prices, monthly caps and the workspace's
    per-prospect ceiling, so no path to a paid vendor can skip a cap."""
    _workspace(container, workspace_id)  # fail early, with a clear message, if it is missing
    settings = container.settings
    return Meter(
        container.uow,
        workspace_id,
        prices={**DEFAULT_PRICES, **settings.provider_prices},
        budget=BudgetPolicy.live_from(settings.monthly_caps_micro_usd),
    )


def assemble(container: Container, workspace_id: str, providers: Providers) -> Pipeline:
    settings = container.settings
    uow = container.uow
    _workspace(container, workspace_id)  # fail early, with a clear message, if it is missing
    budget = BudgetPolicy.live_from(settings.monthly_caps_micro_usd)
    meter = build_meter(container, workspace_id)
    llm_prices = {**DEFAULT_LLM_PRICES, **settings.llm_prices}
    search = MeteredSearch(providers.search, meter)
    llm = MeteredLlm(providers.llm, meter, prices=llm_prices)
    writer = MeteredLlm(providers.copy_llm, meter, prices=llm_prices) if providers.copy_llm else llm
    registry = MeteredRegistry(providers.registry, meter) if providers.registry else None
    # The shared directory goes first and is never cached: every lookup is a ledger row, so the
    # hit rate and what it saved can be read back.
    finders = [MeteredFinder(DirectoryFinder(uow, workspace_id), meter, ttl=None)] + [
        MeteredFinder(f, meter) for f in providers.finders
    ]
    verifier = MeteredVerifier(providers.verifier, meter)
    resolver = MeteredResolver(providers.resolver, meter) if providers.resolver else None

    stages: list[Stage] = [
        ResearchStage(ResearchDeps(search, llm, registry)),
        GateStage(),
        ContactsStage(),
        EmailStage(EmailDeps(finders, verifier, resolver)),
        CopyStage(writer),
    ]
    jobs: list[Job] = []
    if resolver is not None:
        jobs.append(CatchAllPoller(uow, workspace_id, resolver))
    mailboxes = mailboxes_for(container, workspace_id, providers)
    has_mailbox = providers.mailbox is not None or _any_mailbox(container, workspace_id)
    if has_mailbox:
        stages.append(DeliverStage(mailboxes))
        jobs.append(SentSync(uow, workspace_id, mailboxes))
        jobs.append(
            InboxSync(uow, workspace_id, mailboxes, PrivacyService(uow, workspace_id, mailboxes))
        )
        if isinstance(mailboxes, StoredMailboxes):
            jobs.append(MailboxHealth(mailboxes))

    intake = IntakeService(uow, workspace_id, search)
    # First in the tick: credits that appeared (a new period, a grant) release waiting work
    # before this tick's pipeline looks for it.
    jobs.insert(0, ResumeService(uow, workspace_id, intake))
    runner = Runner(uow, workspace_id, stages, Guards(budget))
    return Pipeline(
        runner=runner,
        tick=Tick(uow, workspace_id, runner, jobs),
        review=ReviewService(uow, workspace_id, writer),
        runs=RunService(uow, workspace_id),
        intake=intake,
        meter=meter,
        search=search,
        stage_names=[stage.name for stage in stages],
        has_mailbox=has_mailbox,
    )


def mailboxes_for(
    container: Container, workspace_id: str, providers: Providers | None = None
) -> Mailboxes:
    """The workspace's connected mailboxes, or the one mailbox a test or script injected."""
    if providers is not None and providers.mailbox is not None:
        return one(providers.mailbox)
    settings = container.settings
    return StoredMailboxes(
        container.uow, workspace_id, apps=build_oauth_apps(settings),
        timeout=settings.mailbox_timeout_seconds,
    )  # fmt: skip


def _any_mailbox(container: Container, workspace_id: str) -> bool:
    with container.uow(workspace_id) as uow:
        return bool(uow.mailboxes.all())


def execute_run(
    pipeline: Pipeline,
    container: Container,
    workspace_id: str,
    request: RunRequest,
    *,
    run_id: str | None = None,
) -> RunReport:
    """Optionally look for new companies, then run the pipeline. Used by the CLI and the worker."""
    extra: dict[str, Counter[str]] = {}
    if request.mode is not RunMode.MANUAL:
        found = discover_companies(
            pipeline, container, workspace_id, request.campaign, request.discover
        )
        # Shown on the Runs page, so a search that found only known companies says so.
        extra["discovery"] = Counter(
            {"new leads": found.added, "already leads": found.already_leads}
        )
    return pipeline.runner.run_pipeline(
        limit=request.limit, only=set(request.only) or None, run_id=run_id, extra_counts=extra
    )


@dataclass(frozen=True)
class Discovery:
    added: int = 0
    already_leads: int = 0


def discover_companies(
    pipeline: Pipeline, container: Container, workspace_id: str, campaign_name: str, count: int
) -> Discovery:
    """Search the web for companies that fit the campaign and add them as discovered targets."""
    with container.uow(workspace_id) as uow:
        campaign = uow.campaigns.by_name(campaign_name)
    if campaign is None:
        raise LookupError(f"no campaign named {campaign_name!r}")
    if not (campaign.icp_description or "").strip():
        raise ValueError(
            f"describe the ideal customer on the {campaign_name!r} campaign first: "
            "discovery searches for companies that fit it"
        )
    with container.uow(workspace_id) as uow:
        quota, _ = quota_in(uow, utcnow())
    if not quota.engine:
        return Discovery()
    left = quota.remaining(UsageStep.DISCOVERY)
    if left is not None:
        count = min(count, left)  # never search for companies there is no credit to add
    if count <= 0:
        log.info("discovery_skipped", reason="no discovery credit left")
        return Discovery()
    with container.uow(workspace_id) as uow:
        known = uow.companies.known_domains()
    query = discovery_query(campaign.icp_description or "")
    found = discover_candidates(pipeline.search, [query], per_query=count, skip=known)
    report = pipeline.intake.run(
        found.rows,
        source=ImportSource.CLI,
        company_source=CompanySource.DISCOVERY,
        campaign_id=campaign.id,
    )
    added = report.count(ImportRowStatus.ACCEPTED)
    log.info(
        "discovery_done", asked=count, new_candidates=len(found.rows),
        already_leads=found.already_leads, added=added,
    )  # fmt: skip
    return Discovery(added, found.already_leads)


def writer_or_none(settings: Settings) -> LlmClient | None:
    """The writer model's raw client, built once per process; None if no model is set up."""
    from outbound.providers.errors import ProviderError

    try:
        return build_llm(settings, model=settings.llm_copy_model)
    except ProviderError:
        return None


def search_or_none(settings: Settings) -> SearchProvider | None:
    """Tavily's raw client, built once per process; None when no key is set."""
    return build_search(settings) if settings.tavily_api_key.get_secret_value() else None


def meter_writer(container: Container, workspace_id: str, writer: LlmClient) -> LlmClient:
    """The writer behind this workspace's meter (revisions asked for on Review)."""
    prices = {**DEFAULT_LLM_PRICES, **container.settings.llm_prices}
    return MeteredLlm(writer, build_meter(container, workspace_id), prices=prices)


def meter_search(container: Container, workspace_id: str, search: SearchProvider) -> SearchProvider:
    return MeteredSearch(search, build_meter(container, workspace_id))


def metered_writer_or_none(container: Container, workspace_id: str) -> LlmClient | None:
    """The writer model behind the meter, for revisions asked for on Review; None if no model
    is configured (Review then says so instead of failing at start-up)."""
    writer = writer_or_none(container.settings)
    return meter_writer(container, workspace_id, writer) if writer else None


def metered_search_or_none(container: Container, workspace_id: str) -> SearchProvider | None:
    """Tavily behind the meter, or None when no key is set (name targets then wait for you)."""
    search = search_or_none(container.settings)
    return meter_search(container, workspace_id, search) if search else None
