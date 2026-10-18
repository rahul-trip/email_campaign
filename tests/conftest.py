"""Test-wide fixtures."""

from __future__ import annotations

import pytest
from tenacity import wait_none

import outbound.providers.http as http_module
from outbound.config import Settings


@pytest.fixture(autouse=True)
def no_retry_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retries must not sleep in tests."""
    monkeypatch.setattr(http_module, "_DEFAULT_WAIT", wait_none())


_PROVIDER_ENV = (
    "DATABASE_URL",
    "HUNTER_API_KEY",
    "ZEROBOUNCE_API_KEY",
    "ORBISEARCH_API_KEY",
    "MYEMAILVERIFIER_API_KEY",
    "ENRICHLEY_API_KEY",
    "SCRUBBY_API_KEY",
    "SCRUBBY_BASE_URL",
    "TAVILY_API_KEY",
    "IMAP_HOST",
    "IMAP_PORT",
    "IMAP_USE_SSL",
    "EMAIL_ADDRESS",
    "EMAIL_PASSWORD",
    "FROM_NAME",
    "DRAFTS_FOLDER",
    "SENT_FOLDER",
    "INBOX_FOLDER",
    "COMPANIES_HOUSE_API_KEY",
    "LLM_PROVIDER",
    "LLM_MODEL",
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "COPILOT_API_KEY",
    "FINDER_CHAIN",
    "VERIFIER",
    "CATCH_ALL_RESOLVER",
)


@pytest.fixture(autouse=True)
def clean_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer's exported keys must never change what a test sees."""
    for name in _PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def no_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never read a developer's .env: real keys there must not change what a test sees."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
