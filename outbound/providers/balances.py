"""What a vendor's account has left, from the vendor's own free balance call.

Only the vendors that have one: Hunter (searches left this period), and ZeroBounce,
MyEmailVerifier, OrbiSearch, MillionVerifier and BounceBan (credits). None of these calls
spends a credit. Any failure answers ``None``, which means *unknown*, never zero: a vendor is
not treated as empty because a call failed.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from outbound.logging import get_logger

log = get_logger(__name__)

TIMEOUT_SECONDS = 8.0


@dataclass(frozen=True)
class Balance:
    remaining: float
    unit: str  # "searches" or "credits"
    note: str = ""  # for example "resets 2026-12-16"

    @property
    def empty(self) -> bool:
        return self.remaining <= 0

    def label(self) -> str:
        left = f"{self.remaining:g} {self.unit} left"
        return f"{left}, {self.note}" if self.note else left


def _number(value: object) -> float | None:
    try:
        return float(str(value))
    except ValueError:
        return None


def _hunter(key: str, client: httpx.Client) -> Balance | None:
    data = client.get("https://api.hunter.io/v2/account", headers={"X-API-KEY": key}).json() or {}
    data = data.get("data") or {}
    searches = ((data.get("requests") or {}).get("searches")) or {}
    left = _number(searches.get("remaining"))
    if left is None:
        return None
    reset = str(data.get("reset_date") or "")
    return Balance(left, "searches", f"resets {reset}" if reset else "")


def _zerobounce(key: str, client: httpx.Client) -> Balance | None:
    left = _number(
        client.get("https://api.zerobounce.net/v2/getcredits", params={"api_key": key})
        .json()
        .get("Credits")
    )
    # -1 is how ZeroBounce answers a key it does not know: that is a refused key, not a balance.
    return None if left is None or left < 0 else Balance(left, "credits")


def _myemailverifier(key: str, client: httpx.Client) -> Balance | None:
    url = f"https://client.myemailverifier.com/verifier/getcredits/{key}"
    left = _number(client.get(url).json().get("credits"))
    return None if left is None else Balance(left, "credits")


def _orbisearch(key: str, client: httpx.Client) -> Balance | None:
    answer = client.get("https://api.orbisearch.com/v1/credits", headers={"X-API-Key": key})
    left = _number(answer.json().get("credits"))
    return None if left is None else Balance(left, "credits")


def _millionverifier(key: str, client: httpx.Client) -> Balance | None:
    # The answer's shape is not documented beyond a refused key ({"result": "error", ...}):
    # anything without a number in ``credits`` is "unknown", never zero.
    answer = client.get("https://api.millionverifier.com/api/v3/credits", params={"api": key})
    left = _number(answer.json().get("credits"))
    return None if left is None else Balance(left, "credits")


def _bounceban(key: str, client: httpx.Client) -> Balance | None:
    answer = client.get("https://api.bounceban.com/v1/account", headers={"Authorization": key})
    left = _number(answer.json().get("available_credits"))
    # -1 is how BounceBan says "unlimited" (custom plans): that is not a balance to show.
    return None if left is None or left < 0 else Balance(left, "credits")


_VENDORS = {
    "hunter": _hunter,
    "zerobounce": _zerobounce,
    "myemailverifier": _myemailverifier,
    "orbisearch": _orbisearch,
    "millionverifier": _millionverifier,
    "bounceban": _bounceban,
}
HAS_BALANCE = frozenset(_VENDORS)


def balance(vendor: str, key: str, client: httpx.Client | None = None) -> Balance | None:
    """The vendor's remaining balance, or ``None`` when it has no balance call, there is no key,
    or the call failed."""
    ask = _VENDORS.get(vendor)
    if ask is None or not key.strip():
        return None
    http = client or httpx.Client(timeout=TIMEOUT_SECONDS)
    try:
        found = ask(key.strip(), http)
    except Exception as error:  # noqa: BLE001 - a balance is a convenience: never break a page
        log.warning("vendor_balance_unreadable", vendor=vendor, error_type=type(error).__name__)
        return None
    finally:
        if client is None:
            http.close()
    return found
