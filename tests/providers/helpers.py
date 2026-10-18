"""Shared helpers for adapter tests: fixtures, a mock HTTP client, canned responses."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

FIXTURES = Path(__file__).parent / "fixtures"

Handler = Callable[[httpx.Request], httpx.Response]


def fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text())
    return data


def respond(name: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=fixture(name))


def always(response: httpx.Response) -> Handler:
    return lambda request: response


def mock_client(handler: Handler) -> httpx.Client:
    """An httpx client that answers from ``handler`` instead of the network."""
    return httpx.Client(transport=httpx.MockTransport(handler))
