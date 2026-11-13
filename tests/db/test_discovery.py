"""Finding companies from several sources, screening them against the brief, adding the best.

The world here has a start-up directory (standing in for Y Combinator) and a web search whose
results are list articles; the model reads each article for the companies it names and screens
everything found against the campaign's brief.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy import Engine

from outbound.bootstrap import container_for
from outbound.config import Settings
from outbound.db.platform import PlatformUnitOfWorkFactory
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.entities import DiscoveryCandidate
from outbound.domain.enums import CandidateVerdict, CompanySource, CompanyStatus
from outbound.pipeline import Pipeline, discover_companies
from outbound.providers.errors import ProviderError
from outbound.providers.ports import CompanyMention, PageLink, PageText, SearchHit, SourceQuery
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


def test_a_page_that_only_mentions_a_company_is_not_taken_for_its_website(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    # The real run: a data site's profile of "Zenobe Energy" became the lead's website.
    ws, pipeline, world, container = setup(engine, factory, platform)
    world.directory.mentions = []
    world.search.hits = [
        SearchHit(
            url="https://profiles.example/zenobe-energy",
            title="Zenobe Energy company profile",
            snippet="Zenobe Energy owns battery storage.",
        )
    ]
    world.llm.replies["extract"] = {
        "companies": [{"name": "Zenobe Energy", "website": "", "what_it_says": "BESS owner."}]
    }
    assert run(pipeline, container, ws, 5, "run-1").added == 0
    with factory(ws) as uow:
        [zenobe] = uow.candidates.for_run("run-1")
    assert zenobe.verdict is CandidateVerdict.UNRESOLVED and zenobe.domain is None


def test_a_domain_that_only_contains_a_short_name_is_not_taken_for_the_company(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    # The real run: SONI (the Northern Ireland grid operator) got soniassociates.net.
    ws, pipeline, world, container = setup(engine, factory, platform)
    world.directory.mentions = []
    world.search.hits = [SearchHit(url="https://www.soniassociates.net/", title="SONI Associates")]
    world.llm.replies["extract"] = {
        "companies": [{"name": "SONI", "website": "", "what_it_says": "A grid operator."}]
    }
    assert run(pipeline, container, ws, 5, "run-1").added == 0
    with factory(ws) as uow:
        [soni] = uow.candidates.for_run("run-1")
    assert soni.verdict is CandidateVerdict.UNRESOLVED and soni.domain is None


def test_a_website_the_article_links_to_is_taken_without_a_search(
    engine: Engine,
    factory: UnitOfWorkFactory,
    platform: PlatformUnitOfWorkFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The page names Fingrid and links to it, but its text states no website.
    ws, pipeline, world, container = setup(engine, factory, platform)
    world.directory.mentions = []
    asked: list[bool] = []

    def extract(urls: list[str], *, links: bool = False) -> list[PageText]:
        asked.append(links)
        return [
            PageText(
                url=url,
                text="Ten grid operators, among them Fingrid.",
                links=(
                    PageLink(text="Fingrid", url="https://www.fingrid.fi/en/"),
                    PageLink(text="Contact us", url="https://news.example/contact"),
                ),
            )
            for url in urls
        ]

    monkeypatch.setattr(world.search, "extract", extract)
    world.llm.replies["extract"] = {
        "companies": [{"name": "Fingrid", "website": "", "what_it_says": "Finnish TSO."}]
    }
    assert run(pipeline, container, ws, 5, "run-1").added == 1
    with factory(ws) as uow:
        [fingrid] = uow.candidates.for_run("run-1")
    assert asked == [True]  # the article was read with its links
    assert fingrid.verdict is CandidateVerdict.ACCEPTED and fingrid.domain == "fingrid.fi"
    assert not any("Fingrid" in q for q in world.search.searches)  # no website lookup was made


def test_a_website_that_holds_the_company_name_is_taken(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, world, container = setup(engine, factory, platform)
    world.directory.mentions = []
    world.search.hits = [
        SearchHit(url="https://profiles.example/zenobe-energy", title="Zenobe Energy profile"),
        SearchHit(url="https://www.zenobeenergy.com/about", title="About us"),
    ]
    world.llm.replies["extract"] = {
        "companies": [{"name": "Zenobe Energy", "website": "", "what_it_says": "BESS owner."}]
    }
    assert run(pipeline, container, ws, 5, "run-1").added == 1
    with factory(ws) as uow:
        [zenobe] = uow.candidates.for_run("run-1")
    assert zenobe.domain == "zenobeenergy.com"


def test_a_company_whose_website_was_not_found_waits_to_be_looked_up_again(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    # Before, an unresolved company was remembered as screened and never tried again, so a
    # better website lookup could not rescue it.
    ws, pipeline, world, container = setup(engine, factory, platform)
    world.llm.replies["extract"] = {
        "companies": [{"name": "Mystery Power", "website": "", "what_it_says": "A grid firm."}]
    }
    run(pipeline, container, ws, 5, "run-1")
    with factory(ws) as uow:
        [campaign] = uow.campaigns.all()
        by_name = {c.name: c.verdict for c in uow.candidates.for_run("run-1")}
        waiting = uow.candidates.waiting(campaign.id, 10)
    assert by_name["Mystery Power"] is CandidateVerdict.UNRESOLVED
    assert by_name["Gridcast"] is CandidateVerdict.ACCEPTED  # has its lead, so it does not wait
    assert [c.name for c in waiting] == ["Mystery Power"]


def roles(**by_name: tuple[str, int]) -> Callable[[str], dict[str, object]]:
    """A screening reply giving each named company ``(role, score)``; the rest are buyers at 80."""

    def reply(user: str) -> dict[str, object]:
        import re

        out = []
        for n, name in re.findall(r"^(\d+)\. ([^(\n]+?)(?: \(|\n|$)", user, re.MULTILINE):
            role, score = next(
                (v for k, v in by_name.items() if k.lower() in name.lower()), ("buyer", 80)
            )
            out.append({"n": int(n), "role": role, "score": score, "reason": f"{name} is {role}"})
        return {"companies": out}

    return reply


def screened(
    engine: Engine,
    factory: UnitOfWorkFactory,
    platform: PlatformUnitOfWorkFactory,
    reply: Callable[[str], dict[str, object]],
) -> dict[str, DiscoveryCandidate]:
    ws, pipeline, world, container = setup(engine, factory, platform)
    world.llm.replies["screen"] = reply
    run(pipeline, container, ws, 5, "run-1")
    with factory(ws) as uow:
        return {c.name: c for c in uow.candidates.for_run("run-1")}


def test_a_vendor_does_not_fit_however_high_it_scores(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    # The live run: four software vendors passed on 50 to 55 although the model called them
    # vendors, because "too little text" and "a vendor" both scored in the fifties.
    found = screened(engine, factory, platform, roles(Windwise=("vendor", 75)))
    windwise = found["Windwise"]
    assert windwise.verdict is CandidateVerdict.REJECTED
    assert windwise.reason.startswith("vendor:")
    assert found["Gridcast"].verdict is CandidateVerdict.ACCEPTED


def test_a_company_the_text_does_not_place_needs_a_higher_score_than_a_buyer(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    found = screened(
        engine,
        factory,
        platform,
        roles(Windwise=("unclear", 55), Gridcast=("unclear", 65), Rival=("buyer", 52)),
    )
    verdicts = {name: c.verdict for name, c in found.items()}
    assert verdicts["Windwise"] is CandidateVerdict.REJECTED  # 55 is not enough when unplaced
    assert verdicts["Gridcast"] is CandidateVerdict.ACCEPTED
    assert verdicts["Rival Forecasting"] is CandidateVerdict.ACCEPTED  # a buyer passes at 50


def test_a_role_the_model_makes_up_counts_as_unclear(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    found = screened(engine, factory, platform, roles(Windwise=("partner", 55)))
    assert found["Windwise"].verdict is CandidateVerdict.REJECTED


PSE = SearchHit(
    url="https://www.pse.pl/",
    title="PSE - Polskie Sieci Elektroenergetyczne",
    snippet="Polskie Sieci Elektroenergetyczne is the Polish transmission system operator.",
)


def lookup_world(  # type: ignore[no-untyped-def]
    engine: Engine,
    factory: UnitOfWorkFactory,
    platform: PlatformUnitOfWorkFactory,
    pick: object,
):
    ws, pipeline, world, container = setup(engine, factory, platform)
    world.directory.mentions = []
    world.search.hits = [PSE]
    world.llm.replies["extract"] = {
        "companies": [
            {"name": "Polskie Sieci Elektroenergetyczne", "website": "", "what_it_says": "TSO."}
        ]
    }
    world.llm.replies["website"] = pick
    return ws, pipeline, container


def test_the_model_picks_a_websites_abbreviated_domain_by_number(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    # Live: pse.pl was in the results for the full name but its domain is an abbreviation.
    ws, pipeline, container = lookup_world(engine, factory, platform, {"n": 1})
    assert run(pipeline, container, ws, 5, "run-1").added == 1
    with factory(ws) as uow:
        [pse] = uow.candidates.for_run("run-1")
    assert pse.verdict is CandidateVerdict.ACCEPTED and pse.domain == "pse.pl"


@pytest.mark.parametrize("pick", [{"n": 0}, {"n": 7}, {"n": "1"}, {"n": True}, "not json"])
def test_a_pick_of_none_junk_or_a_number_not_offered_leaves_the_website_unresolved(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory, pick: object
) -> None:
    ws, pipeline, container = lookup_world(engine, factory, platform, pick)
    assert run(pipeline, container, ws, 5, "run-1").added == 0
    with factory(ws) as uow:
        [pse] = uow.candidates.for_run("run-1")
    assert pse.verdict is CandidateVerdict.UNRESOLVED and pse.domain is None


def test_a_failed_pick_leaves_the_website_unresolved(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    def down(user: str) -> dict[str, object]:
        raise ProviderError("fake-llm", "down")

    ws, pipeline, container = lookup_world(engine, factory, platform, down)
    assert run(pipeline, container, ws, 5, "run-1").added == 0
    with factory(ws) as uow:
        [pse] = uow.candidates.for_run("run-1")
    assert pse.verdict is CandidateVerdict.UNRESOLVED


def test_a_company_still_without_a_website_after_a_second_look_is_dropped(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, container = lookup_world(engine, factory, platform, {"n": 0})
    run(pipeline, container, ws, 5, "run-1")
    run(pipeline, container, ws, 5, "run-2")  # looks again at what could not be placed
    with factory(ws) as uow:
        [pse] = uow.candidates.for_run("run-2")
        [campaign] = uow.campaigns.all()
        waiting = uow.candidates.waiting(campaign.id, 10)
    assert pse.verdict is CandidateVerdict.REJECTED and "second look" in pse.reason
    assert waiting == []  # and is not tried again by the third run


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


def test_a_failing_web_search_leaves_the_other_sources_and_the_run_standing(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, world, container = setup(engine, factory, platform)

    def down(query: str, **_: object) -> list[SearchHit]:
        raise ProviderError("tavily", "503 after retries")

    world.search.search = down
    world.directory.mentions = [yc("Gridcast", "gridcast.io"), yc("Mystery", "")]
    found = run(pipeline, container, ws, 5, "run-1")
    assert found.added == 1  # the directory's company still became a lead
    with factory(ws) as uow:
        verdicts = {c.name: c.verdict for c in uow.candidates.for_run("run-1")}
    assert verdicts["Mystery"] is CandidateVerdict.UNRESOLVED  # its website search failed
