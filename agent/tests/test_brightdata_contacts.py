"""agent/tests/test_brightdata_contacts.py — BrightDataContactProvider unit tests.

All network calls are mocked (requests.post / requests.get) — zero real API
calls, and no real sleeping (poll_interval_seconds=0 in tests).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from agent.domain.models import Company
from agent.providers.contacts.brightdata import BrightDataContactProvider
from agent.providers.discovery.base import ProviderError

COMPANY = Company(name="Renewco", domain="renewco.io", url="https://renewco.io")


def _resp(json_body, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.json.return_value = json_body
    resp.text = str(json_body)
    return resp


def _make_provider(**overrides) -> BrightDataContactProvider:
    defaults = dict(
        api_key="test-key",
        dataset_id="gd_test_dataset",
        per_call_delay_seconds=0,
        poll_interval_seconds=0,
        max_poll_attempts=5,
    )
    defaults.update(overrides)
    return BrightDataContactProvider(**defaults)


@patch("agent.providers.contacts.brightdata.requests.get")
@patch("agent.providers.contacts.brightdata.requests.post")
def test_resolve_happy_path(mock_post, mock_get):
    mock_post.return_value = _resp({"snapshot_id": "snap123"})
    mock_get.side_effect = [
        _resp({"status": "ready"}),
        _resp([{"name": "Alice Tester", "position": "VP of Sales",
                 "url": "https://linkedin.com/in/alice", "about": "Loves renewables"}]),
    ]

    provider = _make_provider()
    contact = provider.resolve(COMPANY, ["VP of Sales"])

    assert contact is not None
    assert contact.full_name == "Alice Tester"
    assert contact.title == "VP of Sales"
    assert contact.linkedin_url == "https://linkedin.com/in/alice"
    assert contact.eccentricities == "Loves renewables"


@patch("agent.providers.contacts.brightdata.requests.get")
@patch("agent.providers.contacts.brightdata.requests.post")
def test_trigger_body_includes_search_url(mock_post, mock_get):
    mock_post.return_value = _resp({"snapshot_id": "snap123"})
    mock_get.side_effect = [_resp({"status": "ready"}), _resp([])]

    provider = _make_provider()
    provider.resolve(COMPANY, ["CTO"])

    sent_body = mock_post.call_args.kwargs["json"]
    assert isinstance(sent_body, list)
    assert "linkedin.com/search/results/people" in sent_body[0]["url"]
    assert "CTO" in sent_body[0]["url"]
    sent_params = mock_post.call_args.kwargs["params"]
    assert sent_params["dataset_id"] == "gd_test_dataset"


@patch("agent.providers.contacts.brightdata.requests.get")
@patch("agent.providers.contacts.brightdata.requests.post")
def test_no_profiles_found_tries_next_title_then_returns_none(mock_post, mock_get):
    mock_post.return_value = _resp({"snapshot_id": "snap123"})
    mock_get.side_effect = [
        _resp({"status": "ready"}), _resp([]),   # title 1: no results
        _resp({"status": "ready"}), _resp([]),   # title 2: no results
    ]

    provider = _make_provider()
    contact = provider.resolve(COMPANY, ["VP of Sales", "CTO"])

    assert contact is None
    assert mock_post.call_count == 2


@patch("agent.providers.contacts.brightdata.requests.get")
@patch("agent.providers.contacts.brightdata.requests.post")
def test_snapshot_failed_status_returns_empty(mock_post, mock_get):
    mock_post.return_value = _resp({"snapshot_id": "snap123"})
    mock_get.side_effect = [_resp({"status": "failed"})]

    provider = _make_provider()
    contact = provider.resolve(COMPANY, ["VP of Sales"])

    assert contact is None


@patch("agent.providers.contacts.brightdata.requests.get")
@patch("agent.providers.contacts.brightdata.requests.post")
def test_poll_timeout_returns_empty(mock_post, mock_get):
    mock_post.return_value = _resp({"snapshot_id": "snap123"})
    mock_get.return_value = _resp({"status": "running"})  # never becomes ready

    provider = _make_provider(max_poll_attempts=3)
    contact = provider.resolve(COMPANY, ["VP of Sales"])

    assert contact is None
    assert mock_get.call_count == 3


def test_missing_api_key_raises():
    with pytest.raises(ProviderError, match="BRIGHTDATA_API_KEY"):
        BrightDataContactProvider(api_key="", dataset_id="gd_x")


def test_missing_dataset_id_raises():
    with pytest.raises(ProviderError, match="BRIGHTDATA_LINKEDIN_DATASET_ID"):
        BrightDataContactProvider(api_key="test-key", dataset_id="")


@patch("agent.providers.contacts.brightdata.requests.post")
def test_trigger_retries_on_429_then_succeeds(mock_post):
    rate_limited = _resp({}, status_code=429)
    rate_limited.ok = False
    mock_post.side_effect = [rate_limited, _resp({"snapshot_id": "snap123"})]

    with patch("agent.providers.contacts.brightdata.requests.get") as mock_get:
        mock_get.side_effect = [_resp({"status": "ready"}), _resp([])]
        provider = _make_provider()
        provider.resolve(COMPANY, ["VP of Sales"])

    assert mock_post.call_count == 2
