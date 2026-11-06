"""Finding companies from several sources, screening them against the brief, adding the best.

The world here has a start-up directory (standing in for Y Combinator) and a web search whose
results are list articles; the model reads each article for the companies it names and screens
everything found against the campaign's brief.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import Engine

from outbound.bootstrap import container_for
from outbound.config import Settings
from outbound.db.platform import PlatformUnitOfWorkFactory
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import CandidateVerdict, CompanySource, CompanyStatus
from outbound.pipeline import Pipeline, discover_companies
from outbound.providers.ports import CompanyMention, SearchHit, SourceQuery
from outbound.services.discovery import PER_SOURCE
from tests.db.test_credits import started, used
from tests.stages.fakes import screen_all
from tests.stages.world import World

ARTICLE = "https://news.example/top-grid-start-ups"


def yc(name: str, domain: str) -> CompanyMention:
    return CompanyMention(
        name=name,
        domain=domain,
        description=f"{name} builds software for grid operators.",
        source="yc_directory",
        source_url=f"https://www.ycombinator.com/companies/{domain.split('.')[0]}",
        evidence="Y Combinator Winter 2022",
    )


def setup(engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory):  # type: ignore[no-untyped-def]
    ws, pipeline, world = started(engine, factory, platform)
    world.directory.mentions = [yc("Gridcast", "gridcast.io"), yc("Rival Forecasting", "rival.io")]
    world.search.hits = [SearchHit(url=ARTICLE, title="Ten grid start-ups to watch")]
    world.llm.replies["extract"] = {
        "companies": [
            {"name": "Gridcast", "website": "", "what_it_says": "Gridcast raised a seed round."},
            {"name": "Windwise", "website": "windwise.de", "what_it_says": "Wind forecasts."},
        ]
    }
    world.llm.replies["screen"] = screen_all(80, Rival=10)
    return ws, pipeline, world, container_for(Settings(_env_file=None), engine)


def run(pipeline: Pipeline, container, ws: str, count: int, run_id: str):  # type: ignore[no-untyped-def]
    return discover_companies(pipeline, container, ws, "default", count, run_id=run_id)


def test_companies_from_every_source_are_merged_screened_and_only_fits_become_leads(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, _, container = setup(engine, factory, platform)
    found = run(pipeline, container, ws, 5, "run-1")
    assert found.added == 2
    assert used(factory, ws)["discovery"] == 2  # credits only for leads
    with factory(ws) as uow:
        candidates = {c.name: c for c in uow.candidates.for_run("run-1")}
        leads = {c.domain: c for c in uow.companies.due(CompanyStatus.NEW, 50)}
    assert set(leads) == {"gridcast.io", "windwise.de"}
    gridcast = candidates["Gridcast"]
    assert gridcast.sources == ("yc_directory", "articles")  # found twice, kept once
    assert ARTICLE in gridcast.source_urls and "seed round" in gridcast.evidence
    assert gridcast.verdict is CandidateVerdict.ACCEPTED and gridcast.company_id
    rival = candidates["Rival Forecasting"]
    assert rival.verdict is CandidateVerdict.REJECTED and rival.reason == "a competitor"
    assert "rival.io" not in leads


def test_a_second_run_reads_nothing_again_and_screens_nothing_again(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, world, container = setup(engine, factory, platform)
    run(pipeline, container, ws, 5, "run-1")
    screened, read = world.llm.calls.count("screen"), world.llm.calls.count("extract")
    again = run(pipeline, container, ws, 5, "run-2")
    assert again.added == 0
    assert world.llm.calls.count("screen") == screened  # every company was known
    assert world.llm.calls.count("extract") == read  # the article was read already


def test_a_company_whose_website_cannot_be_confirmed_is_kept_but_not_added(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, world, container = setup(engine, factory, platform)
    world.directory.mentions = []
    world.llm.replies["extract"] = {
        "companies": [{"name": "Mystery Power", "website": "", "what_it_says": "A grid firm."}]
    }
    assert run(pipeline, container, ws, 5, "run-1").added == 0
    with factory(ws) as uow:
        [mystery] = uow.candidates.for_run("run-1")
    assert mystery.verdict is CandidateVerdict.UNRESOLVED and mystery.domain is None


def test_fits_beyond_the_runs_count_are_kept_for_later(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, _, container = setup(engine, factory, platform)
    assert run(pipeline, container, ws, 1, "run-1").added == 1
    with factory(ws) as uow:
        verdicts = sorted(c.verdict.value for c in uow.candidates.for_run("run-1"))
    assert verdicts == ["accepted", "over_limit", "rejected"]


def test_the_brief_is_drafted_on_the_first_run_and_steers_the_sources(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, world, container = setup(engine, factory, platform)
    run(pipeline, container, ws, 5, "run-1")
    with factory(ws) as uow:
        [campaign] = uow.campaigns.all()
    assert campaign.icp_brief and campaign.icp_brief["keywords"] == [
        "grid forecasting",
        "load forecasting",
    ]
    assert world.directory.queries[0].keywords == ("grid forecasting", "load forecasting")
    assert "grid forecasting" in world.search.searches[0]  # the articles search the brief


def test_each_search_is_shown_on_the_run_with_its_source_and_angle(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    from outbound.services.runs import RunRequest, RunService

    ws, pipeline, world, container = setup(engine, factory, platform)
    world.llm.replies["discovery"] = {
        "queries": [{"q": "top grid forecasting start-ups in Europe", "angle": "a ranking"}]
    }
    runs = RunService(factory, ws)
    queued = runs.queue(RunRequest())
    run(pipeline, container, ws, 5, queued.id)
    searches = runs.searches(queued.id)
    by_source = {s.source: s for s in searches}
    assert by_source["yc_directory"].found == 2
    article = next(s for s in searches if s.angle == "a ranking")
    assert article.query == "top grid forecasting start-ups in Europe"
    assert article.pages == (ARTICLE,)


def test_without_a_model_the_directory_still_finds_companies(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    """No model: no articles can be read and nothing screened by a model, but a directory
    entry that names the brief's words is still a fit."""
    from dataclasses import replace

    from outbound.pipeline import assemble

    ws, _, _, container = setup(engine, factory, platform)
    world = World()
    world.directory.mentions = [yc("Gridcast", "gridcast.io")]
    with factory(ws) as uow:
        [campaign] = uow.campaigns.all()
        uow.campaigns.update(campaign.id, {"icp_brief": {"keywords": ["grid operators"]}})
        uow.commit()
    pipeline = replace(assemble(container, ws, world.providers()), llm=None)
    assert run(pipeline, container, ws, 5, "run-1").added == 1
    assert world.llm.calls == []


def _history(factory: UnitOfWorkFactory, ws: str) -> None:
    """An older campaign whose directory finds never qualified and whose articles always did."""
    with factory(ws) as uow:
        old = uow.campaigns.create("old", ["CTO"])
        lead = uow.companies.create(
            domain="winner.io", source=CompanySource.DISCOVERY, campaign_id=old.id
        )
        for status in (CompanyStatus.RESEARCHED, CompanyStatus.QUALIFIED):
            lead = uow.companies.transition(lead.id, status, expected_version=lead.row_version)
        for n in range(12):
            for source, company_id in (("yc_directory", None), ("articles", lead.id)):
                uow.candidates.add(
                    campaign_id=old.id, run_id=None, name=f"{source}{n}",
                    name_key=f"{source}{n}", sources=[source], company_id=company_id,
                    verdict=CandidateVerdict.ACCEPTED,
                )  # fmt: skip
        uow.commit()


def test_a_source_whose_leads_qualify_is_asked_first_and_a_poor_one_for_less(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, world, container = setup(engine, factory, platform)
    _history(factory, ws)
    searched_before: list[int] = []
    asked: Callable[..., list[CompanyMention]] = world.directory.find

    def find(query: SourceQuery, *, limit: int) -> list[CompanyMention]:
        searched_before.append(len(world.search.searches))
        return asked(query, limit=limit)

    world.directory.find = find
    run(pipeline, container, ws, 5, "run-1")
    assert searched_before[0] > 0  # the articles went first
    assert world.directory.limits == [PER_SOURCE // 2]


def test_the_campaigns_qualified_leads_are_examples_to_find_more_like(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, world, container = setup(engine, factory, platform)
    with factory(ws) as uow:
        [campaign] = uow.campaigns.all()
        lead = uow.companies.create(
            domain="best.io", source=CompanySource.MANUAL, campaign_id=campaign.id
        )
        for status in (CompanyStatus.RESEARCHED, CompanyStatus.QUALIFIED):
            lead = uow.companies.transition(lead.id, status, expected_version=lead.row_version)
        uow.commit()
    run(pipeline, container, ws, 5, "run-1")
    assert "best.io" in world.directory.queries[0].seed_domains
