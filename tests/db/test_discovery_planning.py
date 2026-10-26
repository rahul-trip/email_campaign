"""Finding new companies every run (not the same top results): what is searched, and why."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine

from outbound.bootstrap import container_for
from outbound.config import Settings
from outbound.db.platform import PlatformUnitOfWorkFactory
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.discovery import clean, fallback_queries, normal, regions
from outbound.domain.enums import EntityType
from outbound.pipeline import discover_companies
from outbound.providers.ports import SearchHit
from outbound.services.discovery import plan_queries
from tests.db.test_credits import started
from tests.stages.fakes import FakeLlm

BASE = "companies offering products or services for: grid forecasting"
PROFILE = {"geographic_focus": "UK, Germany and the US", "industry": "Energy analytics"}


def test_queries_are_compared_by_words_not_spacing_or_punctuation() -> None:
    assert normal("Grid  forecasting, in the UK!") == normal("grid forecasting in the uk")


def test_a_models_queries_are_cleaned_of_repeats_junk_and_overlong_text() -> None:
    cleaned = clean(
        ["New angle", "new  ANGLE", "", 7, "x " * 40, "Another angle", "Third", "Fourth"],
        used=["third"],
        limit=2,
    )
    assert cleaned == ["New angle", "Another angle"]


def test_the_senders_regions_come_first_in_the_fixed_angles() -> None:
    assert regions(PROFILE) == ["UK", "Germany", "the US"]
    found = fallback_queries(BASE, PROFILE, used=[], limit=4)
    assert found[:3] == [f"{BASE} in UK", f"{BASE} in Germany", f"{BASE} in the US"]
    assert fallback_queries(BASE, PROFILE, used=found[:3], limit=1) == [
        f"{BASE} mid-sized companies"
    ]


def test_the_first_run_is_the_plain_search_then_every_run_takes_new_angles() -> None:
    llm = FakeLlm({"discovery": {"queries": ["wind farm operators in Germany", "solar traders"]}})
    first = plan_queries(llm=llm, base=BASE, profile=PROFILE, icp="grid", used=[], count=3)
    assert first == [BASE, "wind farm operators in Germany", "solar traders"]
    second = plan_queries(llm=llm, base=BASE, profile=PROFILE, icp="grid", used=first, count=3)
    assert BASE not in second and "solar traders" not in second  # nothing is repeated
    assert len(second) == 3  # the model's two were repeats, so fixed angles filled the gap
    assert second[0].startswith(BASE)


def test_without_a_model_or_with_nonsense_the_fixed_angles_still_vary_the_search() -> None:
    plain = plan_queries(llm=None, base=BASE, profile=PROFILE, icp="grid", used=[BASE], count=2)
    assert plain == [f"{BASE} in UK", f"{BASE} in Germany"]
    garbled = FakeLlm({"discovery": {"queries": "not a list"}})
    assert plan_queries(llm=garbled, base=BASE, profile={}, icp="g", used=[BASE], count=1)


def test_what_the_model_is_told_is_the_seller_and_what_was_already_searched() -> None:
    llm = FakeLlm()
    plan_queries(
        llm=llm, base=BASE, profile=PROFILE, icp="grid forecasting", used=["old one"], count=2
    )
    told = llm.users["discovery"]
    assert "Energy analytics" in told and "UK, Germany and the US" in told
    assert "old one" in told and "grid forecasting" in told


def test_each_run_remembers_its_searches_and_the_next_run_does_not_repeat_them(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, world = started(engine, factory, platform)
    container = container_for(Settings(_env_file=None), engine)
    world.search.hits = [
        SearchHit(url=f"https://company{n}.com/about", title="About us", snippet="")
        for n in range(3)
    ]
    discover_companies(pipeline, container, ws, "default", 1, run_id="run-1")
    discover_companies(pipeline, container, ws, "default", 1, run_id="run-2")
    with factory(ws) as uow:
        events = uow.events.latest(EntityType.WORKSPACE, ws, "discovery_query", 20)
    queries = [e.data["query"] for e in events]
    assert len(queries) == len(set(queries)) >= 2  # never the same search twice
    assert queries[0].startswith("companies offering")  # the plain search came first
    assert {e.data["run_id"] for e in events} == {"run-1", "run-2"}

    assert datetime.now(UTC) - events[0].created_at < timedelta(minutes=5)


def test_a_runs_page_can_list_its_searches(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    from outbound.services.runs import RunRequest, RunService

    ws, pipeline, world = started(engine, factory, platform)
    container = container_for(Settings(_env_file=None), engine)
    world.search.hits = [
        SearchHit(url=f"https://shop{n}.com/about", title="About us", snippet="") for n in range(2)
    ]
    runs = RunService(factory, ws)
    run = runs.queue(RunRequest())
    discover_companies(pipeline, container, ws, "default", 1, run_id=run.id)
    [first, *_] = runs.searches(run.id)
    assert first.query.startswith("companies offering") and first.new_leads == 1
