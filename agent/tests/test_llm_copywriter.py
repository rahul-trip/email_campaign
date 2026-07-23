"""agent/tests/test_llm_copywriter.py — LlmCopywriter unit tests.

All network calls are mocked (requests.post) — zero real API calls.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from agent.config.models import LlmConfig, SenderProfile
from agent.domain.models import Company, Contact
from agent.providers.copywriter.llm_copywriter import LlmCopywriter
from agent.providers.discovery.base import ProviderError

COMPANY = Company(name="Renewco", domain="renewco.io", url="https://renewco.io",
                   description="Renewable forecasting for grid operators")
CONTACT = Contact(full_name="Alice Tester", title="VP of Sales",
                   eccentricities="Loves marathon running")
SENDER = SenderProfile(
    company_name="TestCo",
    value_propositions=("Fast ML forecasting",),
    technologies=("machine learning", "forecasting"),
    narrative="TestCo builds ML forecasting tools.",
)


class FakeConfig:
    signature_name = "Test User"
    signature_title = "CPO"


def _mock_response(content: str, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.json.return_value = {"choices": [{"message": {"content": content}}]}
    resp.text = content
    return resp


def _make_copywriter(**overrides) -> LlmCopywriter:
    llm = LlmConfig(provider="anthropic", model="claude-sonnet-5", **overrides)
    return LlmCopywriter(llm=llm, sender=SENDER, per_call_delay_seconds=0)


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("agent.providers.copywriter.llm_copywriter.requests.post")
def test_happy_path_parses_response(mock_post):
    body = json.dumps({
        "pitch_email": "Hi Alice, pitch body here.",
        "follow_up": "Following up.",
        "commonalities": ["Shared ML focus", "Both in forecasting", "Aligned mission"],
    })
    mock_post.return_value = _mock_response(body)

    cw = _make_copywriter()
    result = cw.write(COMPANY, CONTACT, FakeConfig())

    assert result.pitch_email == "Hi Alice, pitch body here."
    assert result.follow_up == "Following up."
    assert result.commonalities == "• Shared ML focus\n• Both in forecasting\n• Aligned mission"


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("agent.providers.copywriter.llm_copywriter.requests.post")
def test_prompt_contains_sender_and_contact_context(mock_post):
    body = json.dumps({"pitch_email": "x", "follow_up": "y", "commonalities": ["a", "b", "c"]})
    mock_post.return_value = _mock_response(body)

    cw = _make_copywriter()
    cw.write(COMPANY, CONTACT, FakeConfig())

    sent_json = mock_post.call_args.kwargs["json"]
    user_msg = sent_json["messages"][1]["content"]
    assert "TestCo builds ML forecasting tools." in user_msg
    assert "machine learning" in user_msg
    assert "forecasting" in user_msg
    assert "Loves marathon running" in user_msg


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("agent.providers.copywriter.llm_copywriter.requests.post")
def test_fenced_json_response_parses(mock_post):
    body = "```json\n" + json.dumps({
        "pitch_email": "x", "follow_up": "y", "commonalities": "• one\n• two"
    }) + "\n```"
    mock_post.return_value = _mock_response(body)

    cw = _make_copywriter()
    result = cw.write(COMPANY, CONTACT, FakeConfig())

    assert result.pitch_email == "x"
    assert result.commonalities == "• one\n• two"


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("agent.providers.copywriter.llm_copywriter.requests.post")
def test_missing_required_key_raises(mock_post):
    body = json.dumps({"pitch_email": "x", "follow_up": "y"})  # commonalities missing
    mock_post.return_value = _mock_response(body)

    cw = _make_copywriter()
    with pytest.raises(ProviderError, match="commonalities"):
        cw.write(COMPANY, CONTACT, FakeConfig())


def test_missing_api_key_env_var_raises():
    llm = LlmConfig(provider="anthropic", model="claude-sonnet-5")
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ProviderError, match="ANTHROPIC_API_KEY"):
            LlmCopywriter(llm=llm, sender=SENDER, per_call_delay_seconds=0)


def test_unknown_provider_raises():
    llm = LlmConfig(provider="not_a_real_provider", model="x")
    with pytest.raises(ProviderError, match="Unknown llm.provider"):
        LlmCopywriter(llm=llm, sender=SENDER, per_call_delay_seconds=0)


@patch.dict("os.environ", {"COPILOT_API_KEY": "copilot-token"})
@patch("agent.providers.copywriter.llm_copywriter.requests.post")
def test_github_copilot_preset_sends_required_headers(mock_post):
    body = json.dumps({"pitch_email": "x", "follow_up": "y", "commonalities": ["a", "b", "c"]})
    mock_post.return_value = _mock_response(body)

    llm = LlmConfig(provider="github_copilot", model="gpt-4o")
    cw = LlmCopywriter(llm=llm, sender=SENDER, per_call_delay_seconds=0)
    cw.write(COMPANY, CONTACT, FakeConfig())

    call_headers = mock_post.call_args.kwargs["headers"]
    assert call_headers["Authorization"] == "Bearer copilot-token"
    assert call_headers["Editor-Version"] == "vscode/1.85.0"
    assert call_headers["Copilot-Integration-Id"] == "vscode-chat"
    assert mock_post.call_args.args[0] == "https://api.githubcopilot.com/chat/completions"


@patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
@patch("agent.providers.copywriter.llm_copywriter.requests.post")
def test_retries_on_429_then_succeeds(mock_post):
    body = json.dumps({"pitch_email": "x", "follow_up": "y", "commonalities": ["a", "b", "c"]})
    rate_limited = _mock_response("", status_code=429)
    rate_limited.ok = False
    mock_post.side_effect = [rate_limited, _mock_response(body)]

    cw = _make_copywriter()
    result = cw.write(COMPANY, CONTACT, FakeConfig())

    assert result.pitch_email == "x"
    assert mock_post.call_count == 2
