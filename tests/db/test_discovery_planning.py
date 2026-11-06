"""Planning the searches for pages that list companies: from the brief, never the same twice."""

from __future__ import annotations

from sqlalchemy import Engine

from outbound.bootstrap import container_for
from outbound.config import Settings
from outbound.db.platform import PlatformUnitOfWorkFactory
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.brief import Brief
from outbound.domain.discovery import clean, normal, regions
from outbound.domain.enums import EntityType
from outbound.pipeline import discover_companies
from outbound.providers.ports import SearchHit
from outbound.services.discovery import PlannedQuery, plan_queries
from tests.db.test_credits import started
from tests.stages.fakes import FakeLlm

BRIEF = Brief.from_json(
    {
        "summary": "Utilities that forecast load",
        "keywords": ["grid forecasting"],
        "segments": ["utilities"],
        "regions": ["UK", "Germany"],
        "disqualifiers": ["competitor: sells forecasting software"],
        "source_hints": ["association member lists"],
    }
)


def test_queries_are_compared_by_words_not_spacing_or_punctuation() -> None:
    assert normal("Grid  forecasting, in the UK!") == normal("grid forecasting in the uk")


def test_a_models_queries_are_cleaned_of_repeats_junk_and_overlong_text() -> None:
    cleaned = clean(
        ["New angle", "new  ANGLE", "", 7, "x " * 40, "Another angle", "Third", "Fourth"],
        used=["third"],
        limit=2,
    )
    assert cleaned == ["New angle", "Another angle"]


def test_the_senders_regions_are_read_as_separate_places() -> None:
    assert regions({"geographic_focus": "UK, Germany and the US"}) == ["UK", "Germany", "the US"]


def test_the_model_plans_searches_with_their_angle_and_never_repeats_one() -> None:
    llm = FakeLlm(
        {
            "discovery": {
                "queries": [
                    {"q": "UK utility association members", "angle": "members list"},
                    {"q": "grid forecasting start-ups funding 2026", "angle": "round-up"},
                ]
            }
        }
    )
    first = plan_queries(llm=llm, brief=BRIEF, used=[], count=2)
    assert first == [
        PlannedQuery("UK utility association members", "members list"),
        PlannedQuery("grid forecasting start-ups funding 2026", "round-up"),
    ]
    second = plan_queries(llm=llm, brief=BRIEF, used=[p.q for p in first], count=2)
    assert not {p.q for p in second} & {p.q for p in first}  # the brief's words fill the gap
    assert all(p.angle == "from the brief" for p in second)


def test_without_a_model_or_with_nonsense_the_brief_still_gives_searches() -> None:
    plain = plan_queries(llm=None, brief=BRIEF, used=[], count=2)
    assert [p.q for p in plain] == [
        "grid forecasting utilities in UK",
        "grid forecasting utilities in Germany",
    ]
    garbled = FakeLlm({"discovery": {"queries": "not a list"}})
    assert plan_queries(llm=garbled, brief=BRIEF, used=[], count=1)


def test_the_model_is_told_the_brief_and_what_was_already_searched() -> None:
    llm = FakeLlm()
    plan_queries(llm=llm, brief=BRIEF, used=["old one"], count=2)
    told = llm.users["discovery"]
    assert "grid forecasting" in told and "UK, Germany" in told
    assert "competitor: sells forecasting software" in told
    assert "old one" in told
    assert "<untrusted>" in told


def test_each_run_remembers_its_searches_and_the_next_run_does_not_repeat_them(
    engine: Engine, factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws, pipeline, world = started(engine, factory, platform)
    container = container_for(Settings(_env_file=None), engine)
    world.search.hits = [
        SearchHit(url=f"https://list{n}.example/top", title="Top") for n in range(3)
    ]
    discover_companies(pipeline, container, ws, "default", 1, run_id="run-1")
    discover_companies(pipeline, container, ws, "default", 1, run_id="run-2")
    with factory(ws) as uow:
        events = uow.events.latest(EntityType.WORKSPACE, ws, "discovery_query", 20)
    articles = [e.data for e in events if e.data["source"] == "articles"]
    queries = [d["query"] for d in articles]
    assert len(queries) == len(set(queries)) >= 2  # never the same search twice
    assert {d["run_id"] for d in articles} == {"run-1", "run-2"}
    pages = [url for d in articles for url in d["pages"]]
    assert len(pages) == len(set(pages))  # never the same page read twice


def test_the_briefs_searches_never_repeat_one_the_model_just_planned() -> None:
    llm = FakeLlm({"discovery": {"queries": [{"q": "grid forecasting utilities in UK"}]}})
    planned = [p.q for p in plan_queries(llm=llm, brief=BRIEF, used=[], count=2)]
    assert planned == ["grid forecasting utilities in UK", "grid forecasting utilities in Germany"]
