"""Connections to hosts a customer types in cannot reach our own network (Phase 6c)."""

from __future__ import annotations

import socket

import pytest

from outbound.providers.adapters.imap_mailbox import guarded_connect
from outbound.providers.errors import ProviderError
from outbound.providers.netguard import public_address

PUBLIC = "93.184.216.34"


def answers(*ips: str):  # type: ignore[no-untyped-def]
    return lambda host, port: list(ips)


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",  # this machine
        "10.0.0.5",  # the VPC
        "172.17.0.1",  # the Docker bridge
        "192.168.1.10",
        "169.254.169.254",  # the cloud metadata service
        "100.64.0.1",  # carrier-grade NAT
        "0.0.0.0",
        "::1",
        "fd00::1",  # IPv6 private
        "fe80::1",  # IPv6 link-local
        "224.0.0.1",  # multicast
    ],
)
def test_private_and_reserved_addresses_are_refused(ip: str) -> None:
    with pytest.raises(ProviderError, match="private or reserved"):
        public_address(
            "imap", "imap.customer.example", 993, allowed_ports={993}, resolve=answers(ip)
        )


def test_one_private_answer_among_public_ones_is_enough_to_refuse() -> None:
    with pytest.raises(ProviderError):
        public_address(
            "imap", "imap.customer.example", 993, allowed_ports={993},
            resolve=answers(PUBLIC, "10.0.0.5"),
        )  # fmt: skip


def test_only_the_expected_ports_are_allowed() -> None:
    for port in (25, 22, 5432, 6379, 80):
        with pytest.raises(ProviderError, match="port"):
            public_address(
                "imap",
                "imap.customer.example",
                port,
                allowed_ports={993, 143},
                resolve=answers(PUBLIC),
            )


def test_a_public_server_gives_the_address_to_connect_to() -> None:
    assert (
        public_address(
            "imap", "Imap.Customer.Example.", 993, allowed_ports={993}, resolve=answers(PUBLIC)
        )
        == PUBLIC
    )


def test_odd_names_and_failed_lookups_are_refused() -> None:
    for name in ("", "user@host", "host/path", "a b"):
        with pytest.raises(ProviderError):
            public_address("imap", name, 993, allowed_ports={993}, resolve=answers(PUBLIC))

    def fail(host: str, port: int) -> list[str]:
        raise socket.gaierror("no such host")

    with pytest.raises(ProviderError) as caught:
        public_address("imap", "nowhere.example", 993, allowed_ports={993}, resolve=fail)
    assert caught.value.retryable


def test_the_connection_goes_to_the_checked_address_not_the_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DNS answer that changes after the check cannot redirect the connection."""
    dialled: list[tuple[str, int]] = []

    def dial(address: tuple[str, int], timeout: float | None = None) -> socket.socket:
        dialled.append(address)
        raise ConnectionRefusedError

    monkeypatch.setattr(socket, "create_connection", dial)
    with pytest.raises(OSError):
        guarded_connect("imap.customer.example", 993, timeout=5, resolve=answers(PUBLIC))
    assert dialled == [(PUBLIC, 993)]


def test_a_private_server_is_refused_before_any_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("connected"))
    with pytest.raises(ProviderError):
        guarded_connect("imap.customer.example", 993, timeout=5, resolve=answers("10.1.2.3"))
