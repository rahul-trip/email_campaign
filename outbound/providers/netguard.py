"""Guarding connections to hosts a customer types in (an IMAP server, later SMTP).

A customer-supplied host could point at our own network: the cloud metadata service, the
database, anything on a private address. So the host is resolved once, every address it
resolves to must be public, only the expected ports are allowed, and the caller connects to the
address that was checked (with the original name for TLS), so a DNS answer that changes between
the check and the connection cannot slip a private address in.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Collection

from outbound.providers.errors import ProviderError

Resolve = Callable[[str, int], list[str]]


def system_resolve(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def public_address(
    provider: str,
    host: str,
    port: int,
    *,
    allowed_ports: Collection[int],
    resolve: Resolve = system_resolve,
) -> str:
    """The one public IP address to connect to for ``host``, or a ProviderError saying why not."""
    if port not in allowed_ports:
        allowed = ", ".join(str(p) for p in sorted(allowed_ports))
        raise ProviderError(provider, f"port {port} is not allowed; use {allowed}")
    name = host.strip().rstrip(".").lower()
    if not name or any(c in name for c in "/@ "):
        raise ProviderError(provider, "the server name is not valid")
    try:
        addresses = resolve(name, port)
    except (OSError, UnicodeError):
        raise ProviderError(provider, f"cannot find the server {name}", retryable=True) from None
    if not addresses:
        raise ProviderError(provider, f"cannot find the server {name}", retryable=True)
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
        if not ip.is_global or ip.is_multicast:
            raise ProviderError(provider, f"{name} points at a private or reserved address")
    return addresses[0]
