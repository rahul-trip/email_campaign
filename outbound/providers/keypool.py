"""Several keys for one vendor: each call uses one at random, and a bad key is skipped.

The console lets a vendor have up to three live keys (``domain.vendors.MAX_KEYS``). The registry
builds one adapter per key and puts them behind a ``KeyPool``, which looks like a single adapter
of that vendor, so the meter, the ledger and the stages see no difference.

For each call the keys are tried in a random order. A key that is refused (401/403), rate
limited (429) or out of credit at the vendor (Tavily's 432/433, raised as ``BudgetExceeded``) is
passed over for the next; any other failure (the vendor is down, a bad request) would be the same
with every key, so it is raised at once. Only when every key failed does the caller see an error.

A catch-all resolver that answers later keeps its answer in the account that was asked, so its
ticket remembers the key: ``ResolverKeyPool`` prefixes the reference with the key's position.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from typing import Any, cast

from outbound.logging import get_logger
from outbound.providers.errors import (
    BudgetExceeded,
    ProviderAuthError,
    ProviderError,
    RateLimited,
)
from outbound.providers.ports import CatchAllResolver, ResolutionResult, ResolutionTicket

log = get_logger(__name__)

# Failures that belong to one key (or its account), so another key may well work.
_KEY_FAILURES = (ProviderAuthError, RateLimited, BudgetExceeded)


class KeyPool:
    """One adapter per key of the same vendor, used as one."""

    def __init__(
        self,
        members: Sequence[Any],
        *,
        shuffle: Callable[[list[int]], None] = random.shuffle,
    ) -> None:
        if not members:
            raise ValueError("a key pool needs at least one key")
        self._members = list(members)
        self._shuffle = shuffle
        self.name: str = self._members[0].name

    def __len__(self) -> int:
        return len(self._members)

    def _order(self) -> list[int]:
        order = list(range(len(self._members)))
        self._shuffle(order)
        return order

    def _try(self, call: Callable[[Any], Any], order: list[int] | None = None) -> tuple[int, Any]:
        failures: list[ProviderError] = []
        for index in order if order is not None else self._order():
            try:
                return index, call(self._members[index])
            except _KEY_FAILURES as error:
                failures.append(error)
                log.warning(
                    "vendor_key_skipped",
                    vendor=self.name,
                    key=index + 1,
                    error=type(error).__name__,
                    status_code=error.status_code,
                )
        raise failures[-1]  # every key failed; the others are in the log

    def __getattr__(self, attribute: str) -> Any:
        first = getattr(self._members[0], attribute)
        if not callable(first):
            return first

        def call(*args: Any, **kwargs: Any) -> Any:
            return self._try(lambda m: getattr(m, attribute)(*args, **kwargs))[1]

        return call


class ResolverKeyPool(KeyPool):
    """A catch-all resolver with several keys: a queued ticket is polled with the key that
    queued it."""

    def submit(self, email: str) -> ResolutionTicket:
        index, found = self._try(lambda m: m.submit(email))
        ticket = cast(ResolutionTicket, found)
        if ticket.result is not None:
            return ticket
        return ticket.model_copy(update={"ref": f"k{index + 1}:{ticket.ref}"})

    def poll(self, ticket: ResolutionTicket) -> ResolutionResult | None:
        index, ref = 0, ticket.ref
        head, sep, rest = ticket.ref.partition(":")
        if sep and head[:1] == "k" and head[1:].isdigit():
            index, ref = int(head[1:]) - 1, rest
        # A ticket queued before this key was removed (or before pools existed) uses the first.
        member: CatchAllResolver = self._members[index if index < len(self._members) else 0]
        return member.poll(ticket.model_copy(update={"ref": ref}))
