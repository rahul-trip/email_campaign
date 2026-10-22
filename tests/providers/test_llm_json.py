"""ask_json: one more try for a broken, mis-shaped or cut-off reply, and no more than that."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from outbound.providers.errors import ProviderError
from outbound.providers.llm_json import ask_json
from outbound.providers.ports import LlmResult


class Answer(BaseModel):
    people: list[str] = []


class Scripted:
    """Replies (or raises) in order, and records what it was sent."""

    name = "scripted"
    model = "m"

    def __init__(self, *replies: str | Exception) -> None:
        self._replies = list(replies)
        self.users: list[str] = []
        self.temperatures: list[float | None] = []

    def complete(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LlmResult:
        self.users.append(user)
        self.temperatures.append(temperature)
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return LlmResult(text=reply, provider=self.name, model=self.model)


CUT_OFF = ProviderError(
    "scripted", "the reply was cut off at the token limit; raise LLM_MAX_TOKENS"
)


def test_a_good_reply_is_one_call() -> None:
    llm = Scripted('{"people": ["Ada"]}')
    assert ask_json(llm, "s", "u", Answer).people == ["Ada"]
    assert llm.users == ["u"]


def test_the_real_broken_reply_from_the_first_run_is_asked_for_again() -> None:
    # cbinsights.com: the model answered {"people":{ "people": []}  (unbalanced, wrong shape).
    llm = Scripted('{"people":{ "people": []}', '{"people": []}')
    assert ask_json(llm, "s", "u", Answer).people == []
    assert len(llm.users) == 2
    assert "could not be used" in llm.users[1] and llm.users[1].startswith("u")


@pytest.mark.parametrize(
    "first",
    ["no json here at all", '{"people": "not a list"}', CUT_OFF],
    ids=["no object", "wrong shape", "cut off"],
)
def test_each_kind_of_unusable_reply_gets_one_more_try(first: str | Exception) -> None:
    llm = Scripted(first, '{"people": ["Ada"]}')
    assert ask_json(llm, "s", "u", Answer).people == ["Ada"]
    assert len(llm.users) == 2


def test_a_cut_off_reply_is_told_so() -> None:
    llm = Scripted(CUT_OFF, '{"people": []}')
    ask_json(llm, "s", "u", Answer)
    assert "it was cut off" in llm.users[1]


def test_two_unusable_replies_in_a_row_fail_with_the_second_reason() -> None:
    llm = Scripted("nope", '{"people": "x"}')
    with pytest.raises(ProviderError, match="expected shape"):
        ask_json(llm, "s", "u", Answer)
    assert len(llm.users) == 2


def test_a_rate_limit_is_not_asked_for_again_here() -> None:
    llm = Scripted(ProviderError("scripted", "429", retryable=True), '{"people": []}')
    with pytest.raises(ProviderError, match="429"):
        ask_json(llm, "s", "u", Answer)
    assert len(llm.users) == 1


def test_the_temperature_is_passed_on_to_both_tries() -> None:
    llm = Scripted("nope", '{"people": []}')
    ask_json(llm, "s", "u", Answer, temperature=0.2)
    assert llm.temperatures == [0.2, 0.2]
