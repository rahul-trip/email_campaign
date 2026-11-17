"""One model call settles the people the rules left unsure; a failure leaves them unsure."""

from __future__ import annotations

from outbound.domain.placement import Placement
from outbound.providers.errors import ProviderError
from outbound.stages.research.employment import Candidate, judge_people
from tests.stages.fakes import FakeLlm

PEOPLE = [Candidate("Sam Lee", "CTO at Rival | ..."), Candidate("Ann Roe", "Head of Sales")]


def test_the_models_verdicts_are_read_in_order() -> None:
    llm = FakeLlm(
        {
            "employment": {
                "people": [
                    {"n": 1, "verdict": "not_here", "reason": "CTO at Rival"},
                    {"n": 2, "verdict": "unsure", "reason": "no employer"},
                ]
            }
        }
    )
    out = judge_people(llm, "Volue", "volue.com", "grids", PEOPLE)
    assert [p for p, _ in out] == [Placement.NOT_HERE, Placement.UNSURE]
    assert out[0][1] == "CTO at Rival"
    assert llm.calls.count("employment") == 1  # one call for everyone


def test_an_invented_number_or_verdict_changes_nobody() -> None:
    llm = FakeLlm(
        {"employment": {"people": [{"n": 9, "verdict": "not_here"}, {"n": 1, "verdict": "x"}]}}
    )
    out = judge_people(llm, "Volue", "volue.com", "", PEOPLE)
    assert [p for p, _ in out] == [Placement.UNSURE, Placement.UNSURE]


def test_a_model_failure_leaves_everyone_unsure() -> None:
    class Broken(FakeLlm):
        def complete(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise ProviderError("fake-llm", "down")

    out = judge_people(Broken(), "Volue", "volue.com", "", PEOPLE)
    assert [p for p, _ in out] == [Placement.UNSURE, Placement.UNSURE]


def test_nobody_to_judge_makes_no_call() -> None:
    llm = FakeLlm()
    assert judge_people(llm, "Volue", "volue.com", "", []) == []
    assert llm.calls == []
