from __future__ import annotations

import json

import httpx
import pytest

from outbound.config import Settings
from outbound.providers.adapters.llm import PRESETS, OpenAiCompatibleLlm
from outbound.providers.errors import ProviderAuthError, ProviderError
from outbound.providers.llm_json import parse_json_object
from outbound.providers.registry import build_llm
from tests.contract._shared import SECRET
from tests.providers.helpers import Handler, always, mock_client, respond


def build(
    handler: Handler,
    preset: str = "openai",
    *,
    base_url: str = "",
    temperature: float = 0.7,
    max_tokens: int = 1_000,
    reasoning_effort: str = "",
) -> OpenAiCompatibleLlm:
    return OpenAiCompatibleLlm(
        preset,
        "gpt-test",
        SECRET,
        base_url=base_url,
        temperature=temperature,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
        client=mock_client(handler),
    )


def capture() -> tuple[list[httpx.Request], Handler]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return respond("llm/chat.json")

    return seen, handler


def test_reply_text_model_and_token_counts_are_mapped() -> None:
    result = build(always(respond("llm/chat.json"))).complete("sys", "usr")
    assert result.text == '{"hook": "Saw your grid report"}'
    assert (result.provider, result.model) == ("openai", "gpt-test-2026")
    assert (result.input_tokens, result.output_tokens) == (120, 30)


def test_request_shape_and_bearer_key() -> None:
    seen, handler = capture()
    build(handler, temperature=0.2, max_tokens=300).complete("be brief", "write it")
    request = seen[0]
    assert request.url.path == "/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {SECRET}"
    body = json.loads(request.read())
    assert body["messages"] == [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "write it"},
    ]
    assert (body["temperature"], body["max_tokens"]) == (0.2, 300)
    assert "response_format" not in body


def test_per_call_overrides_win() -> None:
    seen, handler = capture()
    build(handler).complete("s", "u", temperature=0.0, max_tokens=50)
    body = json.loads(seen[0].read())
    assert (body["temperature"], body["max_tokens"]) == (0.0, 50)


def test_json_mode_is_requested_only_where_the_endpoint_supports_it() -> None:
    seen, handler = capture()
    build(handler, "openai").complete("s", "u", json_mode=True)
    build(handler, "anthropic").complete("s", "u", json_mode=True)
    assert json.loads(seen[0].read())["response_format"] == {"type": "json_object"}
    assert "response_format" not in json.loads(seen[1].read())


def test_copilot_sends_its_extra_headers() -> None:
    seen, handler = capture()
    build(handler, "github_copilot").complete("s", "u")
    assert seen[0].headers["copilot-integration-id"] == "vscode-chat"
    assert "editor-version" in seen[0].headers


def test_ollama_needs_no_key_and_sends_none() -> None:
    seen, handler = capture()
    llm = OpenAiCompatibleLlm("ollama", "llama3", client=mock_client(handler))
    llm.complete("s", "u")
    assert "authorization" not in seen[0].headers
    assert seen[0].url.host == "localhost"


def test_a_custom_address_is_used() -> None:
    seen, handler = capture()
    build(handler, "openai_compatible", base_url="https://api.groq.test/openai/v1").complete(
        "s", "u"
    )
    assert str(seen[0].url) == "https://api.groq.test/openai/v1/chat/completions"


def test_construction_fails_early_and_clearly() -> None:
    with pytest.raises(ProviderError, match="unknown LLM provider"):
        OpenAiCompatibleLlm("nope", "m", SECRET)
    with pytest.raises(ProviderError, match="no model"):
        OpenAiCompatibleLlm("openai", "", SECRET)
    with pytest.raises(ProviderError, match="LLM_BASE_URL"):
        OpenAiCompatibleLlm("openai_compatible", "m", SECRET)
    with pytest.raises(ProviderAuthError):
        OpenAiCompatibleLlm("openai", "m", "")


@pytest.mark.parametrize(
    "payload", [{}, {"choices": []}, {"choices": [{"message": {"content": " "}}]}]
)
def test_an_unusable_reply_is_an_error(payload: dict[str, object]) -> None:
    with pytest.raises(ProviderError):
        build(always(httpx.Response(200, json=payload))).complete("s", "u")


def test_a_reply_cut_off_at_the_token_limit_says_so() -> None:
    body = {"choices": [{"message": {"content": '{"hook": "half'}, "finish_reason": "length"}]}
    with pytest.raises(ProviderError, match="LLM_MAX_TOKENS"):
        build(always(httpx.Response(200, json=body))).complete("s", "u")


def test_missing_usage_counts_as_zero_tokens() -> None:
    body = {"choices": [{"message": {"content": "hi"}}]}
    result = build(always(httpx.Response(200, json=body))).complete("s", "u")
    assert (result.input_tokens, result.output_tokens, result.model) == (0, 0, "gpt-test")


def test_rate_limits_are_retried_then_succeed() -> None:
    answers = [httpx.Response(429), respond("llm/chat.json")]
    llm = build(lambda request: answers.pop(0))
    assert llm.complete("s", "u").text


def test_a_bad_key_is_not_retried_and_the_message_hides_the_key() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(401)

    with pytest.raises(ProviderAuthError) as caught:
        build(handler).complete("s", "u")
    assert len(calls) == 1
    assert SECRET not in str(caught.value)


def test_every_preset_has_an_address_or_requires_one() -> None:
    assert [name for name, preset in PRESETS.items() if not preset.base_url] == [
        "openai_compatible"
    ]


# ------------------------------------------------------------------ registry


def test_the_registry_uses_the_vendors_own_key_then_the_generic_one() -> None:
    settings = Settings(llm_provider="openai", openai_api_key=SECRET)
    assert build_llm(settings).name == "openai"
    fallback = Settings(llm_provider="openai", llm_api_key=SECRET)
    assert build_llm(fallback).name == "openai"
    with pytest.raises(ProviderAuthError):
        build_llm(Settings(llm_provider="openai"))


# ------------------------------------------------------------------ JSON parsing


@pytest.mark.parametrize(
    "text",
    [
        '{"a": 1}',
        '```json\n{"a": 1}\n```',
        'Here you go:\n{"a": 1}\nHope that helps!',
    ],
)
def test_json_is_found_inside_fences_and_commentary(text: str) -> None:
    assert parse_json_object("llm", text) == {"a": 1}


@pytest.mark.parametrize("text", ["no json here", "{not json}", "[1, 2]", ""])
def test_text_without_a_json_object_is_an_error(text: str) -> None:
    with pytest.raises(ProviderError):
        parse_json_object("llm", text)


def test_reasoning_effort_is_sent_only_when_it_is_set() -> None:
    seen, handler = capture()
    build(handler, "openai_compatible", base_url="https://openrouter.ai/api/v1").complete("s", "u")
    build(
        handler,
        "openai_compatible",
        base_url="https://openrouter.ai/api/v1",
        reasoning_effort="Low",
    ).complete("s", "u")
    assert "reasoning" not in json.loads(seen[0].read())
    assert json.loads(seen[1].read())["reasoning"] == {"effort": "low"}


def test_the_reasoning_effort_and_a_separate_writer_model_come_from_settings() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="openai_compatible",
        llm_base_url="https://openrouter.ai/api/v1",
        llm_model="cheap/research-model",
        llm_api_key=SECRET,
        llm_reasoning_effort="low",
    )
    assert build_llm(settings).model == "cheap/research-model"
    assert build_llm(settings, model="strong/writer-model").model == "strong/writer-model"
