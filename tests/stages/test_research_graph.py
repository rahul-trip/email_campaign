"""Research: the supervisor's routing, the pure fact rules, and the graph with fake providers."""

from __future__ import annotations

import pytest

from outbound.domain.enums import LegalEntityType
from outbound.providers.errors import ProviderError
from outbound.providers.ports import RegistryEntry, SearchHit
from outbound.stages.research.facts import (
    CORPORATE_TYPES,
    IncorporationMarkers,
    best_registry_match,
    classify_legal_entity,
    find_incorporation_markers,
    infer_country,
)
from outbound.stages.research.graph import (
    LEGAL,
    PERSONA,
    SIGNALS,
    SITE,
    ResearchDeps,
    ResearchInput,
    ResearchOutput,
    build_research_graph,
    plan_workers,
    run_research,
)
from tests.stages.fakes import PAGES, FakeLlm, FakeRegistry, FakeSearch

C = LegalEntityType


def base(**kwargs: object) -> ResearchInput:
    values: dict[str, object] = {
        "domain": "acme.co.uk",
        "company_name": "Acme Energy",
        "icp": "Utilities that need forecasts",
        "target_titles": ("CTO", "VP of Sales"),
    }
    values.update(kwargs)
    return ResearchInput(**values)  # type: ignore[arg-type]


# ------------------------------------------------------------------ supervisor routing


def test_the_site_worker_always_runs() -> None:
    assert SITE in plan_workers(base(country_code="US", has_operator_contact=True))


@pytest.mark.parametrize(
    ("country", "runs"), [(None, True), ("GB", True), ("DE", False), ("US", False), ("IN", False)]
)
def test_the_legal_check_runs_only_for_the_uk_or_an_unknown_country(
    country: str | None, runs: bool
) -> None:
    assert (LEGAL in plan_workers(base(country_code=country))) is runs


def test_the_persona_worker_is_skipped_when_the_operator_gave_a_contact() -> None:
    assert PERSONA in plan_workers(base())
    assert PERSONA not in plan_workers(base(has_operator_contact=True))


def test_the_signals_worker_runs_only_when_the_campaign_has_questions() -> None:
    assert SIGNALS not in plan_workers(base())
    assert SIGNALS in plan_workers(base(questions=("Do they trade power?",)))


# ------------------------------------------------------------------ country evidence


@pytest.mark.parametrize(
    ("domain", "text", "code"),
    [
        ("acme.com", "Registered in England and Wales", "GB"),
        ("acme.de", "", "DE"),
        ("acme.co.uk", "", "GB"),
        ("acme.com", "Call us on +49 30 1234 5678", "DE"),
        ("acme.com", "Call +353 1 234 5678", "IE"),
        ("acme.com", "Visit us at LS1 4AP Leeds", "GB"),
        ("acme.com", "Nothing helpful here", None),
        ("acme.io", "", None),
    ],
)
def test_country_is_inferred_from_the_strongest_signal(
    domain: str, text: str, code: str | None
) -> None:
    assert infer_country(domain, text)[0] == code


def test_a_stated_registration_beats_the_domain() -> None:
    assert infer_country("acme.de", "registered in Scotland")[0] == "GB"


# ------------------------------------------------------------------ legal entity


def test_markers_are_found_in_a_footer() -> None:
    markers = find_incorporation_markers("Acme Energy Ltd. Company number 01234567")
    assert (markers.legal_form, markers.company_number) == ("Ltd", "01234567")


def test_scottish_company_numbers_are_recognised() -> None:
    assert find_incorporation_markers("Registered number SC123456").company_number == "SC123456"


def test_no_markers_means_nothing_found() -> None:
    markers = find_incorporation_markers("We make forecasts. Contact us.")
    assert not markers.found and not markers.sole_trader_hint


def entry(**kwargs: str) -> RegistryEntry:
    values = {
        "name": "ACME ENERGY LIMITED",
        "number": "01234567",
        "status": "active",
        "company_type": "ltd",
    }
    values.update(kwargs)
    return RegistryEntry(**values)


def test_an_active_limited_company_at_companies_house_is_a_corporate_subscriber() -> None:
    kind, evidence = classify_legal_entity(IncorporationMarkers(None, None, False), entry())
    assert kind is C.CORPORATE_SUBSCRIBER and "01234567" in evidence


def test_a_footer_marker_is_enough_without_a_registry() -> None:
    kind, _ = classify_legal_entity(IncorporationMarkers("Ltd", None, False), None)
    assert kind is C.CORPORATE_SUBSCRIBER


def test_a_sole_trader_with_nothing_else_is_not_assumed_corporate() -> None:
    kind, _ = classify_legal_entity(IncorporationMarkers(None, None, True), None)
    assert kind is C.SOLE_TRADER_OR_PARTNERSHIP


def test_no_evidence_at_all_stays_unknown_so_the_gate_holds() -> None:
    kind, _ = classify_legal_entity(IncorporationMarkers(None, None, False), None)
    assert kind is C.UNKNOWN


def test_a_registry_match_that_is_not_a_corporate_type_does_not_count() -> None:
    odd = entry(company_type="limited-partnership")
    assert "limited-partnership" not in CORPORATE_TYPES
    kind, _ = classify_legal_entity(IncorporationMarkers(None, None, False), odd)
    assert kind is C.UNKNOWN


def test_only_an_active_entry_with_every_distinctive_word_matches() -> None:
    entries = [
        entry(name="ACME ENERGY LIMITED", status="dissolved"),
        entry(name="ACME LIMITED"),
        entry(name="ACME ENERGY SERVICES LTD", number="07654321"),
    ]
    match = best_registry_match("Acme Energy Ltd", entries)
    assert match is not None and match.number == "07654321"
    assert best_registry_match("Zed Corp", entries) is None
    assert best_registry_match("Ltd", entries) is None


# ------------------------------------------------------------------ the graph


def run(
    inp: ResearchInput,
    *,
    llm: FakeLlm | None = None,
    search: FakeSearch | None = None,
    registry: FakeRegistry | None = None,
) -> tuple[ResearchOutput, FakeLlm, FakeSearch]:
    llm = llm or FakeLlm()
    search = search if search is not None else FakeSearch(PAGES)
    graph = build_research_graph(ResearchDeps(search, llm, registry))
    return run_research(graph, inp), llm, search


def test_a_uk_company_is_researched_end_to_end() -> None:
    registry = FakeRegistry([entry()])
    out, llm, search = run(base(questions=("Do they trade power?",)), registry=registry)
    assert out.research["summary"].startswith("Acme builds")
    assert out.research["hooks"] == ["Their Leeds office opening"]
    assert out.answers == {"Do they trade power?": "Yes, via a trading desk."}
    assert (out.country_code, out.legal_entity_type) == ("GB", C.CORPORATE_SUBSCRIBER)
    assert (out.fit_score, out.fit_reason) == (82, "Utility forecasting is exactly the target.")
    assert [p.name for p in out.people] == ["Jane Doe"]  # a single name is not a person
    assert sorted(llm.calls) == ["fit", "persona", "signals", "site"]
    assert registry.queries == ["Acme Energy"]
    assert len(search.extracted) == 1 and len(search.extracted[0]) == 5


def test_a_manual_lead_with_a_contact_skips_the_persona_and_signals_workers() -> None:
    out, llm, _ = run(base(has_operator_contact=True, country_code="US"))
    assert sorted(llm.calls) == ["fit", "site"]
    assert out.people == ()
    assert out.legal_entity_type is C.UNKNOWN


def test_a_german_company_never_reaches_companies_house() -> None:
    registry = FakeRegistry([entry()])
    out, _, _ = run(base(domain="acme.de", country_code="DE"), registry=registry)
    assert registry.queries == []
    assert out.country_code == "DE"


def test_a_uk_sole_trader_has_no_marker_and_no_registry_match() -> None:
    search = FakeSearch({"https://trader.co.uk": "Bob's boiler servicing in Leeds, LS1 4AP"})
    out, _, _ = run(
        base(domain="trader.co.uk", company_name="Bobs Boilers"),
        search=search,
        registry=FakeRegistry([]),
    )
    assert (out.country_code, out.legal_entity_type) == ("GB", C.UNKNOWN)


def test_an_operator_given_country_is_kept_and_not_second_guessed() -> None:
    out, _, _ = run(base(domain="acme.com", country_code="GB"), search=FakeSearch(PAGES))
    assert out.country_code == "GB"
    assert "given by the operator" in out.research["country_evidence"]


def test_the_country_is_inferred_when_unknown() -> None:
    out, _, _ = run(base())
    assert out.country_code == "GB"
    assert out.research["country_evidence"]


def test_an_unreadable_site_falls_back_to_a_search_and_says_so() -> None:
    search = FakeSearch(
        {}, hits=[SearchHit(url="https://news.example/acme", title="Acme", snippet="Grid software")]
    )
    out, llm, _ = run(base(), search=search)
    assert out.research["thin"] is True
    assert "Acme" in llm.users["site"]


def test_the_persona_worker_falls_back_to_a_public_search_when_there_is_no_team_page() -> None:
    pages = {"https://acme.co.uk": "Acme builds forecasting software."}
    linkedin = "| LinkedIn"
    hits = [
        SearchHit(
            url="https://uk.linkedin.com/in/jane-doe-1?trk=x",
            title=f"Jane Doe - CTO - Acme Energy {linkedin}",
        ),
        SearchHit(
            url="https://linkedin.com/in/other", title=f"Sam Lee - CEO - Different Co {linkedin}"
        ),
        SearchHit(url="https://example.com/jane", title="Jane Doe - CTO - Acme Energy"),
    ]
    out, llm, search = run(base(), search=FakeSearch(pages, hits))
    assert "persona" not in llm.calls
    assert [(p.name, p.title, p.linkedin_url, p.source) for p in out.people] == [
        ("Jane Doe", "CTO", "https://uk.linkedin.com/in/jane-doe-1", "search")
    ]
    assert search.searches[-1].startswith('site:linkedin.com/in "Acme Energy"')


def test_the_fit_score_is_clamped_into_range() -> None:
    llm = FakeLlm({"fit": {"score": 150, "reason": "x"}})
    assert run(base(), llm=llm)[0].fit_score == 100


def test_no_icp_means_no_fit_score_and_no_fit_call() -> None:
    out, llm, _ = run(base(icp=""))
    assert out.fit_score is None and "fit" not in llm.calls


def test_a_reply_that_is_not_json_is_a_provider_error() -> None:
    with pytest.raises(ProviderError, match="no JSON"):
        run(base(), llm=FakeLlm({"site": "Sorry, I cannot help."}))


def test_a_reply_with_the_wrong_shape_is_a_provider_error() -> None:
    with pytest.raises(ProviderError, match="expected shape"):
        run(base(), llm=FakeLlm({"fit": {"score": "high"}}))


def test_notes_and_answers_reach_the_fit_judgement() -> None:
    llm = FakeLlm()
    run(base(notes="met at the expo", questions=("Do they trade power?",)), llm=llm)
    assert "met at the expo" in llm.users["fit"]
    assert "Yes, via a trading desk." in llm.users["fit"]
