"""ask_json: one more try for a broken, mis-shaped or cut-off reply, and no more than that."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from outbound.providers.errors import ProviderError
from outbound.providers.llm_json import ask_json, ask_object
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
        self.max_tokens: list[int | None] = []

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
        self.max_tokens.append(max_tokens)
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


# ----------------------------------------------------------------------------- ask_object


def test_ask_object_returns_the_object_whatever_its_shape() -> None:
    llm = Scripted('Here you go: {"companies": [{"n": 1}], "anything": true}')
    assert ask_object(llm, "s", "u") == {"companies": [{"n": 1}], "anything": True}


def test_ask_object_asks_a_cut_off_reply_again_and_says_why() -> None:
    llm = Scripted(CUT_OFF, '{"companies": []}')
    assert ask_object(llm, "s", "u", temperature=0.1) == {"companies": []}
    assert "it was cut off" in llm.users[1]
    assert llm.temperatures == [0.1, 0.1]


def test_ask_object_sets_no_reply_cap_of_its_own() -> None:
    """The model's configured limit applies: a cap sized for the answer cut a reasoning model's
    answer off in production (screening: 18 failed calls, 334 companies rejected unread)."""
    llm = Scripted(CUT_OFF, '{"a": 1}')
    ask_object(llm, "s", "u")
    assert llm.max_tokens == [None, None]


def test_ask_object_fails_after_one_more_try() -> None:
    llm = Scripted(CUT_OFF, CUT_OFF)
    with pytest.raises(ProviderError, match="cut off"):
        ask_object(llm, "s", "u")
    assert len(llm.users) == 2


def test_ask_object_does_not_retry_a_rate_limit_or_a_json_array() -> None:
    limited = Scripted(ProviderError("scripted", "429", retryable=True), "{}")
    with pytest.raises(ProviderError, match="429"):
        ask_object(limited, "s", "u")
    assert len(limited.users) == 1
    array = Scripted("[1, 2]", "[3]")
    with pytest.raises(ProviderError):
        ask_object(array, "s", "u")
    assert len(array.users) == 2  # "no JSON object" is worth one more try, then it fails
