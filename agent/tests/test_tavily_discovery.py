"""agent/tests/test_tavily_discovery.py — TavilyDiscoveryProvider unit tests.

All network calls are mocked (requests.post) — zero real API calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from agent.providers.discovery.base import ProviderError
from agent.providers.discovery.tavily import TavilyDiscoveryProvider


def _mock_response(results: list[dict], status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.json.return_value = {"results": results}
    resp.text = str(results)
    return resp


@patch("agent.providers.discovery.tavily.requests.post")
def test_discover_maps_results_to_companies(mock_post):
    mock_post.return_value = _mock_response([
        {"title": "Renewco", "url": "https://renewco.io/about", "content": "Renewable forecasting"},
        {"title": "LinkedIn", "url": "https://linkedin.com/company/x", "content": "should be filtered"},
    ])

    provider = TavilyDiscoveryProvider(api_key="test-key", per_call_delay_seconds=0)
    companies = provider.discover(["solar"], "UK", limit=5)

    assert len(companies) == 1
    assert companies[0].name == "Renewco"
    assert companies[0].domain == "renewco.io"
    assert companies[0].description == "Renewable forecasting"


@patch("agent.providers.discovery.tavily.requests.post")
def test_discover_dedupes_by_domain(mock_post):
    mock_post.return_value = _mock_response([
        {"title": "Renewco", "url": "https://renewco.io/about", "content": "a"},
        {"title": "Renewco Blog", "url": "https://renewco.io/blog", "content": "b"},
    ])

    provider = TavilyDiscoveryProvider(api_key="test-key", per_call_delay_seconds=0)
    companies = provider.discover(["solar"], "UK", limit=5)

    assert len(companies) == 1


@patch("agent.providers.discovery.tavily.requests.post")
def test_discover_respects_limit(mock_post):
    mock_post.return_value = _mock_response([
        {"title": f"Co{i}", "url": f"https://co{i}.example", "content": "x"} for i in range(5)
    ])

    provider = TavilyDiscoveryProvider(api_key="test-key", per_call_delay_seconds=0)
    companies = provider.discover(["solar"], "UK", limit=2)

    assert len(companies) == 2


@patch("agent.providers.discovery.tavily.requests.post")
def test_query_sent_includes_keywords_and_location(mock_post):
    mock_post.return_value = _mock_response([])

    provider = TavilyDiscoveryProvider(api_key="test-key", per_call_delay_seconds=0)
    provider.discover(["solar energy", "grid analytics"], "United Kingdom", limit=5)

    sent_body = mock_post.call_args.kwargs["json"]
    assert sent_body["query"] == "solar energy grid analytics United Kingdom"
    assert sent_body["api_key"] == "test-key"
    assert sent_body["max_results"] == 5


def test_missing_api_key_raises():
    with pytest.raises(ProviderError, match="TAVILY_API_KEY"):
        TavilyDiscoveryProvider(api_key="", per_call_delay_seconds=0)


@patch("agent.providers.discovery.tavily.requests.post")
def test_retries_on_429_then_succeeds(mock_post):
    rate_limited = _mock_response([], status_code=429)
    rate_limited.ok = False
    mock_post.side_effect = [
        rate_limited,
        _mock_response([{"title": "Renewco", "url": "https://renewco.io", "content": "x"}]),
    ]

    provider = TavilyDiscoveryProvider(api_key="test-key", per_call_delay_seconds=0)
    companies = provider.discover(["solar"], "UK", limit=5)

    assert len(companies) == 1
    assert mock_post.call_count == 2
