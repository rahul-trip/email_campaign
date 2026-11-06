"""Drafting a campaign's ideal-customer brief from its description and the sender profile."""

from __future__ import annotations

from outbound.domain.brief import CompanyType
from outbound.domain.entities import Campaign
from outbound.providers.errors import ProviderError
from outbound.services.brief import draft_brief
from tests.stages.fakes import FakeLlm

CAMPAIGN = Campaign(
    id="c1",
    workspace_id="w1",
    name="grid",
    target_titles=("Head of Trading",),
    min_fit_score=60,
    research_questions=("Do they trade power?",),
    cadence_days=(0, 3, 8),
    icp_description="Utilities that forecast load",
)
PROFILE = {
    "industry": "Energy analytics",
    "geographic_focus": "UK and Germany",
    "value_propositions": ["Day-ahead forecasts 30% more accurate"],
    "technologies": ["Machine learning"],
    "target_verticals": ["Utilities"],
    "narrative": "We build forecasting models.",
    "signature_name": "Not for the brief",
}


def test_the_brief_is_drafted_from_the_campaign_and_what_the_writer_may_use() -> None:
    llm = FakeLlm()
    brief = draft_brief(llm, campaign=CAMPAIGN, profile=PROFILE)
    assert brief.keywords == ("grid forecasting", "load forecasting")
    assert brief.disqualifiers == ("competitor: sells forecasting software",)
    sent = llm.users["brief"]
    for expected in (
        "Utilities that forecast load",
        "Head of Trading",
        "Do they trade power?",
        "Day-ahead forecasts 30% more accurate",
        "UK and Germany",
        "Utilities",
    ):
        assert expected in sent
    assert "Not for the brief" not in sent  # the signature is not who we look for
    assert "<untrusted>" in sent  # the profile is fenced: the operator typed it, a file may hold it


class Broken:
    name = "broken"
    model = "broken"

    def complete(self, *args: object, **kwargs: object) -> object:
        raise ProviderError("broken", "down")


def test_without_a_model_the_brief_is_built_from_what_is_known() -> None:
    for llm in (None, Broken(), FakeLlm({"brief": "not json"})):
        brief = draft_brief(llm, campaign=CAMPAIGN, profile=PROFILE)  # type: ignore[arg-type]
        assert brief.summary == "Utilities that forecast load"
        assert brief.regions == ("UK", "Germany")
        assert brief.segments == ("Utilities",)
        assert brief.company_type is CompanyType.ANY
