"""Metered providers: every paid call goes through here, so none can skip the cache or the cap.

``Meter`` is the shared mechanism: look the request up in the ledger, refuse it if it would
break a cap, make the call, and record what it cost. The ``Metered*`` classes wrap a port so a
stage holds an ordinary ``EmailFinder`` (or verifier, resolver, search provider) and never knows
the ledger exists. Each ledger write happens in its own short transaction, so no database
connection is held open while a vendor answers.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from outbound.db.types import utcnow
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import CallOutcome
from outbound.logging import get_logger
from outbound.metering.budget import BudgetPolicy, check_budget
from outbound.providers.errors import BudgetExceeded
from outbound.providers.ports import (
    CatchAllResolver,
    CompanyRegistry,
    EmailFinder,
    EmailVerifier,
    FinderResult,
    LlmClient,
    LlmResult,
    PageText,
    PersonQuery,
    RegistryEntry,
    ResolutionResult,
    ResolutionTicket,
    SearchHit,
    SearchProvider,
    VerificationResult,
)
from outbound.providers.pricing import DEFAULT_LLM_PRICES, DEFAULT_PRICES, llm_cost, price_of

# How long a stored answer stays good. People change jobs, so addresses are re-checked after a
# quarter; web pages after a month.
FINDER_TTL = timedelta(days=90)
VERIFIER_TTL = timedelta(days=90)
RESOLVER_TTL = timedelta(days=90)
SEARCH_TTL = timedelta(days=30)
NEWS_TTL = timedelta(days=7)  # "recent" must stay recent when a lead is researched again

log = get_logger(__name__)


# --------------------------------------------------------------------------- who the call is for


@dataclass(frozen=True)
class CallScope:
    """The run, company and contact a call is made for, so the ledger can attribute the cost."""

    run_id: str | None = None
    company_id: str | None = None
    contact_id: str | None = None


_scope: ContextVar[CallScope | None] = ContextVar("call_scope", default=None)


@contextmanager
def call_scope(
    *,
    run_id: str | None = None,
    company_id: str | None = None,
    contact_id: str | None = None,
) -> Iterator[None]:
    """Attribute every metered call inside the block. Unnamed fields keep the outer value."""
    outer = current_scope()
    inner = replace(
        outer,
        run_id=run_id or outer.run_id,
        company_id=company_id or outer.company_id,
        contact_id=contact_id or outer.contact_id,
    )
    token = _scope.set(inner)
    try:
        yield
    finally:
        _scope.reset(token)


def current_scope() -> CallScope:
    return _scope.get() or CallScope()


# --------------------------------------------------------------------------- the meter


def _canonical(value: Any) -> Any:
    """Make equivalent requests identical: case, spacing and key order do not matter."""
    if isinstance(value, str):
        return value.strip().casefold()
    if isinstance(value, Mapping):
        return {str(k): _canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    return value


def request_hash(provider: str, operation: str, request: Mapping[str, Any]) -> str:
    payload = json.dumps(
        [provider, operation, _canonical(request)], sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Meter:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        workspace_id: str,
        *,
        prices: Mapping[str, int | None] | None = None,
        budget: BudgetPolicy | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._uow = uow_factory
        self._workspace_id = workspace_id
        self.prices: Mapping[str, int | None] = DEFAULT_PRICES if prices is None else prices
        self._budget = budget or BudgetPolicy()
        self._clock = clock

    def price(self, provider: str, operation: str) -> int:
        return price_of(dict(self.prices), provider, operation)

    def lookup(
        self,
        provider: str,
        operation: str,
        request: Mapping[str, Any],
        *,
        ttl: timedelta,
        decode: Callable[[dict[str, Any]], Any],
    ) -> Any | None:
        """A stored answer to this exact request, recorded as a free cache hit; else ``None``."""
        digest = request_hash(provider, operation, request)
        scope = current_scope()
        with self._uow(self._workspace_id) as uow:
            stored = uow.calls.cached_response(provider, operation, digest, self._clock() - ttl)
            if stored is None:
                return None
            try:
                result = decode(stored)
            except (ValueError, KeyError):
                return None  # an unreadable entry is a miss, not an error
            uow.calls.record(
                provider=provider,
                operation=operation,
                request_hash=digest,
                outcome=CallOutcome.CACHE_HIT,
                run_id=scope.run_id,
                company_id=scope.company_id,
                contact_id=scope.contact_id,
            )
            uow.commit()
        log.debug("provider_call", provider=provider, operation=operation, outcome="cache_hit")
        return result

    def record(
        self,
        provider: str,
        operation: str,
        request: Mapping[str, Any],
        *,
        outcome: CallOutcome,
        cost: int = 0,
        response: dict[str, Any] | None = None,
        latency_ms: int | None = None,
    ) -> None:
        scope = current_scope()
        with self._uow(self._workspace_id) as uow:
            uow.calls.record(
                provider=provider,
                operation=operation,
                request_hash=request_hash(provider, operation, request),
                outcome=outcome,
                cost_micro_usd=cost,
                response=response,
                latency_ms=latency_ms,
                run_id=scope.run_id,
                company_id=scope.company_id,
                contact_id=scope.contact_id,
            )
            uow.commit()
        emit = log.warning if outcome is CallOutcome.ERROR else log.info
        emit(
            "provider_call",
            provider=provider,
            operation=operation,
            outcome=outcome.value,
            cost_micro_usd=cost,
            latency_ms=latency_ms,
        )

    def call[T](
        self,
        *,
        provider: str,
        operation: str,
        request: Mapping[str, Any],
        run: Callable[[], T],
        encode: Callable[[T], dict[str, Any]],
        decode: Callable[[dict[str, Any]], T],
        found: Callable[[T], bool] = lambda _: True,
        cost: Callable[[T], int] | None = None,
        ttl: timedelta | None = None,
    ) -> T:
        """Cache, cap, call, record. ``found`` false makes the entry a miss (still reusable)."""
        if ttl is not None:
            cached: T | None = self.lookup(provider, operation, request, ttl=ttl, decode=decode)
            if cached is not None:
                return cached

        self._enforce_cap(provider, operation, request)

        started = time.monotonic()
        try:
            result = run()
        except Exception as error:
            self.record(
                provider,
                operation,
                request,
                outcome=CallOutcome.ERROR,
                response={"error": type(error).__name__},
                latency_ms=_elapsed_ms(started),
            )
            raise
        self.record(
            provider,
            operation,
            request,
            outcome=CallOutcome.HIT if found(result) else CallOutcome.MISS,
            cost=cost(result) if cost else self.price(provider, operation),
            response=encode(result),
            latency_ms=_elapsed_ms(started),
        )
        return result

    def _enforce_cap(self, provider: str, operation: str, request: Mapping[str, Any]) -> None:
        scope = current_scope()
        with self._uow(self._workspace_id) as uow:
            reason = check_budget(
                self._budget,
                uow,
                provider=provider,
                expected_cost=self.price(provider, operation),
                company_id=scope.company_id,
                now=self._clock(),
            )
            if reason is None:
                return
            uow.calls.record(
                provider=provider,
                operation=operation,
                request_hash=request_hash(provider, operation, request),
                outcome=CallOutcome.BLOCKED_BY_CAP,
                run_id=scope.run_id,
                company_id=scope.company_id,
                contact_id=scope.contact_id,
            )
            uow.commit()
        log.warning(
            "provider_call_blocked",
            provider=provider,
            operation=operation,
            outcome=CallOutcome.BLOCKED_BY_CAP.value,
            reason=reason,
        )
        raise BudgetExceeded(provider, reason)


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


# --------------------------------------------------------------------------- wrapped ports


class MeteredFinder:
    def __init__(self, inner: EmailFinder, meter: Meter, *, ttl: timedelta = FINDER_TTL) -> None:
        self._inner = inner
        self._meter = meter
        self._ttl = ttl
        self.name = inner.name

    def find(self, person: PersonQuery, domain: str) -> FinderResult:
        price = self._meter.price(self.name, "find")
        return self._meter.call(
            provider=self.name,
            operation="find",
            request={"person": person.model_dump(exclude_none=True), "domain": domain},
            run=lambda: self._inner.find(person, domain),
            encode=lambda r: r.model_dump(mode="json"),
            decode=FinderResult.model_validate,
            found=lambda r: r.email is not None,
            cost=lambda r: price if r.billed else 0,
            ttl=self._ttl,
        )


class MeteredVerifier:
    def __init__(
        self, inner: EmailVerifier, meter: Meter, *, ttl: timedelta = VERIFIER_TTL
    ) -> None:
        self._inner = inner
        self._meter = meter
        self._ttl = ttl
        self.name = inner.name

    def verify(self, email: str) -> VerificationResult:
        price = self._meter.price(self.name, "verify")
        return self._meter.call(
            provider=self.name,
            operation="verify",
            request={"email": email},
            run=lambda: self._inner.verify(email),
            encode=lambda r: r.model_dump(mode="json"),
            decode=VerificationResult.model_validate,
            cost=lambda r: price if r.billed else 0,
            ttl=self._ttl,
        )


class MeteredResolver:
    """Submissions are paid and never replayed; finished answers are cached by address.

    A ticket is a promise that depends on the vendor's own state, so it is not cached. The
    answer it eventually yields is, under its own operation name, so asking again about the
    same address costs nothing.
    """

    def __init__(
        self, inner: CatchAllResolver, meter: Meter, *, ttl: timedelta = RESOLVER_TTL
    ) -> None:
        self._inner = inner
        self._meter = meter
        self._ttl = ttl
        self.name = inner.name

    def submit(self, email: str) -> ResolutionTicket:
        known: ResolutionResult | None = self._meter.lookup(
            self.name, "resolve", {"email": email}, ttl=self._ttl, decode=_decode_resolution
        )
        if known is not None:
            return ResolutionTicket(ref="cached", email=email, provider=self.name, result=known)

        price = self._meter.price(self.name, "resolve")
        ticket = self._meter.call(
            provider=self.name,
            operation="submit",
            request={"email": email},
            run=lambda: self._inner.submit(email),
            encode=lambda t: t.model_dump(mode="json"),
            decode=ResolutionTicket.model_validate,
            cost=lambda t: 0 if t.result is not None and not t.result.billed else price,
        )
        if ticket.result is not None:
            self._remember(email, ticket.result)
        return ticket

    def poll(self, ticket: ResolutionTicket) -> ResolutionResult | None:
        result = self._inner.poll(ticket)
        if result is not None:
            self._remember(ticket.email, result)
        return result

    def _remember(self, email: str, result: ResolutionResult) -> None:
        self._meter.record(
            self.name,
            "resolve",
            {"email": email},
            outcome=CallOutcome.HIT,
            response=result.model_dump(mode="json"),
        )


def _decode_resolution(stored: dict[str, Any]) -> ResolutionResult:
    return ResolutionResult.model_validate(stored)


class MeteredSearch:
    def __init__(self, inner: SearchProvider, meter: Meter, *, ttl: timedelta = SEARCH_TTL) -> None:
        self._inner = inner
        self._meter = meter
        self._ttl = ttl
        self.name = inner.name

    def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        topic: str = "general",
        days: int | None = None,
    ) -> list[SearchHit]:
        request: dict[str, object] = {"query": query, "max_results": max_results}
        if topic != "general":  # only when set, so earlier cached searches still match
            request["topic"] = topic
        if days:
            request["days"] = days
        return self._meter.call(
            provider=self.name,
            operation="search",
            request=request,
            run=lambda: self._inner.search(query, max_results=max_results, topic=topic, days=days),
            encode=lambda hits: {"items": [h.model_dump(mode="json") for h in hits]},
            decode=lambda stored: [SearchHit.model_validate(i) for i in stored["items"]],
            found=bool,
            ttl=NEWS_TTL if topic == "news" else self._ttl,
        )

    def extract(self, urls: list[str]) -> list[PageText]:
        return self._meter.call(
            provider=self.name,
            operation="extract",
            request={"urls": sorted(urls)},
            run=lambda: self._inner.extract(urls),
            encode=lambda pages: {"items": [p.model_dump(mode="json") for p in pages]},
            decode=lambda stored: [PageText.model_validate(i) for i in stored["items"]],
            found=bool,
            ttl=self._ttl,
        )


class MeteredLlm:
    """Model calls are priced per token and, by default, never replayed.

    Two identical prompts are usually asked for two different drafts, so a cache would be wrong
    for copy. Pass ``ttl`` for a deterministic task such as classification.
    """

    def __init__(
        self,
        inner: LlmClient,
        meter: Meter,
        *,
        prices: Mapping[str, tuple[int, int]] | None = None,
        ttl: timedelta | None = None,
    ) -> None:
        self._inner = inner
        self._meter = meter
        self._prices = dict(DEFAULT_LLM_PRICES if prices is None else prices)
        self._ttl = ttl
        self.name = inner.name
        self.model = inner.model

    def complete(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LlmResult:
        return self._meter.call(
            provider=self.name,
            operation="complete",
            request={
                "model": self.model,
                "system": system,
                "user": user,
                "json_mode": json_mode,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            run=lambda: self._inner.complete(
                system, user, json_mode=json_mode, temperature=temperature, max_tokens=max_tokens
            ),
            encode=lambda r: r.model_dump(mode="json"),
            decode=LlmResult.model_validate,
            cost=lambda r: llm_cost(self._prices, self.model, r.input_tokens, r.output_tokens),
            ttl=self._ttl,
        )


class MeteredRegistry:
    """Registry lookups are free but rate-limited, so repeated names come from the ledger."""

    def __init__(
        self, inner: CompanyRegistry, meter: Meter, *, ttl: timedelta = SEARCH_TTL
    ) -> None:
        self._inner = inner
        self._meter = meter
        self._ttl = ttl
        self.name = inner.name

    def search(self, company_name: str, *, max_results: int = 5) -> list[RegistryEntry]:
        return self._meter.call(
            provider=self.name,
            operation="lookup",
            request={"name": company_name, "max_results": max_results},
            run=lambda: self._inner.search(company_name, max_results=max_results),
            encode=lambda entries: {"items": [e.model_dump(mode="json") for e in entries]},
            decode=lambda stored: [RegistryEntry.model_validate(i) for i in stored["items"]],
            found=bool,
            ttl=self._ttl,
        )
