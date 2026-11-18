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
    ResolutionStatus,
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


def realtime_answer(resolver: CatchAllResolver | None, email: str) -> ResolutionResult | None:
    """A settled answer (valid or invalid) from the real-time resolvers alone, or None. Free of
    waiting: used for an address already held as an unproven catch-all, before it waits (or
    waits again) for an asynchronous resolver. A failing resolver is skipped."""
    if resolver is None:
        return None
    quick = getattr(resolver, "try_realtime", None)
    try:
        if quick is not None:
            found: ResolutionResult | None = quick(email)
            return found
        if getattr(resolver, "realtime", False):
            result = resolver.submit(email).result
            if result is not None and result.status is not ResolutionStatus.UNRESOLVED:
                return result
    except ProviderError as error:
        log.warning("realtime_resolver_failed", resolver=resolver.name, error=type(error).__name__)
    return None


class ResolverChain:
    """Submits to the resolvers in turn; asks the one that took the address later.

    The real-time resolvers (their answer comes with the call) go first, then the asynchronous
    ones (Scrubby: about 72 hours). A real-time resolver that cannot decide hands over to the
    next, and if none decides, the last "unresolved" answer stands. A failing resolver is
    skipped. A ticket still waiting is returned as soon as an asynchronous resolver takes it.
    """

    def __init__(self, resolvers: Sequence[CatchAllResolver]) -> None:
        if not resolvers:
            raise ValueError("a resolver chain needs at least one resolver")
        self._resolvers = sorted(resolvers, key=lambda r: not getattr(r, "realtime", False))
        self._by_name = {r.name: r for r in self._resolvers}
        self.name = self._resolvers[0].name

    def submit(self, email: str) -> ResolutionTicket:
        errors: list[ProviderError] = []
        undecided: ResolutionTicket | None = None
        for resolver in self._resolvers:
            try:
                ticket = resolver.submit(email)
            except ProviderError as error:
                errors.append(error)
                log.warning(
                    "vendor_failed_trying_next", role="resolver", vendor=resolver.name,
                    error=type(error).__name__, status_code=error.status_code,
                )  # fmt: skip
                continue
            if ticket.result is None or ticket.result.status is not ResolutionStatus.UNRESOLVED:
                return ticket  # waiting on an asynchronous resolver, or settled
            undecided = undecided or ticket  # could not decide: the next one may
        if undecided is not None:
            return undecided
        if len(errors) == 1:
            raise errors[0]
        raise ProviderError(self._resolvers[0].name, "; ".join(str(e) for e in errors))

    def try_realtime(self, email: str) -> ResolutionResult | None:
        for resolver in self._resolvers:
            if not getattr(resolver, "realtime", False):
                continue
            try:
                result = resolver.submit(email).result
            except ProviderError:
                continue
            if result is not None and result.status is not ResolutionStatus.UNRESOLVED:
                return result
        return None

    def poll(self, ticket: ResolutionTicket) -> ResolutionResult | None:
        # A ticket saved before the chain existed may name the verifier: the first resolver
        # was the only one then.
        return self._by_name.get(ticket.provider, self._resolvers[0]).poll(ticket)
