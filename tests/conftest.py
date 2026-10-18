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


# Every setting can come from the environment, so every one is cleared: a developer's exported
# value can never change a test. Built from the Settings class, so a new setting is covered
# the day it is added.
_SETTING_ENV = tuple(name.upper() for name in Settings.model_fields)


@pytest.fixture(autouse=True)
def clean_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer's exported keys must never change what a test sees."""
    for name in _SETTING_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def no_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never read a developer's .env: real keys there must not change what a test sees."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
