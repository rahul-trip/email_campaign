"""Backup vendors: when the verifier or the catch-all resolver fails, the next one takes over.

Each vendor in a chain is already metered on its own, so the ledger shows which one was asked
and which one answered. A chain moves on only when a call fails (a refused key, a vendor that is
down, a spend cap reached); a vendor that answers, whatever it says, is the answer. Only when
every vendor fails does the caller see an error, naming each one's.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from outbound.logging import get_logger
from outbound.providers.errors import ProviderError
from outbound.providers.ports import (
    CatchAllResolver,
    EmailVerifier,
    ResolutionResult,
    ResolutionTicket,
    VerificationResult,
)

log = get_logger(__name__)


def _first_that_works[V, T](
    vendors: Sequence[V], name: Callable[[V], str], call: Callable[[V], T], role: str
) -> T:
    errors: list[ProviderError] = []
    for vendor in vendors:
        try:
            return call(vendor)
        except ProviderError as error:
            errors.append(error)
            if len(errors) < len(vendors):
                log.warning(
                    "vendor_failed_trying_next",
                    role=role,
                    vendor=name(vendor),
                    error=type(error).__name__,
                    status_code=error.status_code,
                )
    if len(errors) == 1:
        raise errors[0]
    raise ProviderError(name(vendors[0]), "; ".join(str(e) for e in errors))


class VerifierChain:
    """Verifies with the first verifier that answers, in the order given."""

    def __init__(self, verifiers: Sequence[EmailVerifier]) -> None:
        if not verifiers:
            raise ValueError("a verifier chain needs at least one verifier")
        self._verifiers = list(verifiers)
        self.name = self._verifiers[0].name

    def verify(self, email: str) -> VerificationResult:
        return _first_that_works(
            self._verifiers, lambda v: v.name, lambda v: v.verify(email), "verifier"
        )


class ResolverChain:
    """Submits to the first resolver that takes the address; asks the one that took it later."""

    def __init__(self, resolvers: Sequence[CatchAllResolver]) -> None:
        if not resolvers:
            raise ValueError("a resolver chain needs at least one resolver")
        self._resolvers = list(resolvers)
        self._by_name = {r.name: r for r in self._resolvers}
        self.name = self._resolvers[0].name

    def submit(self, email: str) -> ResolutionTicket:
        return _first_that_works(
            self._resolvers, lambda r: r.name, lambda r: r.submit(email), "resolver"
        )

    def poll(self, ticket: ResolutionTicket) -> ResolutionResult | None:
        # A ticket saved before the chain existed may name the verifier: the first resolver
        # was the only one then.
        return self._by_name.get(ticket.provider, self._resolvers[0]).poll(ticket)
