"""The test suite protects itself: no network, and no leakage from the developer's machine."""

from __future__ import annotations

import os
import socket

import pytest
from pytest_socket import SocketConnectBlockedError

from outbound.config import Settings


def test_a_test_cannot_reach_the_internet() -> None:
    with pytest.raises(SocketConnectBlockedError):
        socket.create_connection(("93.184.216.34", 80), timeout=1)


def test_the_machines_own_environment_never_reaches_the_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The autouse cleanup already ran before this body; anything set here is a new leak."""
    for name in Settings.model_fields:
        assert os.environ.get(name.upper()) is None, f"{name.upper()} leaked into the test"
    monkeypatch.setenv("MONTHLY_CAPS_MICRO_USD", '{"zerobounce": 1}')
    assert Settings(_env_file=None).monthly_caps_micro_usd == {"zerobounce": 1}
