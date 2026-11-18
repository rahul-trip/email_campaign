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
from outbound.domain.credits import credits_for, llm_credits
from outbound.domain.enums import CallOutcome
from outbound.logging import get_logger
from outbound.metering.budget import BudgetPolicy, check_budget
from outbound.providers.errors import BudgetExceeded, ProviderError
from outbound.providers.ports import (
    CatchAllResolver,
    CompanyMention,
    CompanyRegistry,
    EmailFinder,
    EmailVerifier,
    FinderResult,
    LeadSource,
    LlmClient,
    LlmResult,
    PageText,
    PersonQuery,
    RegistryEntry,
    ResolutionResult,
    ResolutionTicket,
    SearchHit,
    SearchProvider,
    SourceQuery,
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
    fresh: bool = False  # ignore stored answers: the operator asked to try again


_scope: ContextVar[CallScope | None] = ContextVar("call_scope", default=None)


@contextmanager
def call_scope(
    *,
    run_id: str | None = None,
    company_id: str | None = None,
    contact_id: str | None = None,
    fresh: bool = False,
) -> Iterator[None]:
    """Attribute every metered call inside the block. Unnamed fields keep the outer value."""
    outer = current_scope()
    inner = replace(
        outer,
        run_id=run_id or outer.run_id,
        company_id=company_id or outer.company_id,
        contact_id=contact_id or outer.contact_id,
        fresh=fresh or outer.fresh,
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
        asked: str = "",
        got: Callable[[Any], str] | None = None,
    ) -> Any | None:
        """A stored answer to this exact request, recorded as a free cache hit; else ``None``."""
        digest = request_hash(provider, operation, request)
        scope = current_scope()
        if scope.fresh:
            return None
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
                detail=_detail(asked, got(result) if got else ""),
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
        reason: str | None = None,
        detail: dict[str, str] | None = None,
        tokens: tuple[str, int, int] | None = None,
    ) -> None:
        """``tokens`` (model, input, output) marks a model call: it uses the model's charge in
        AI credits when one is set."""
        scope = current_scope()
        with self._uow(self._workspace_id) as uow:
            credits = 0
            if cost or tokens:
                # AI credits at the charges in force now, stamped on the row.
                settings, _ = uow.platform_settings.get()
                charge = settings.charge(tokens[0]) if tokens else None
                if tokens and charge:
                    credits = llm_credits(tokens[1], tokens[2], *charge)
                else:
                    credits = credits_for(cost, settings.credit_value_micro_usd)
            uow.calls.record(
                provider=provider,
                operation=operation,
                request_hash=request_hash(provider, operation, request),
                outcome=outcome,
                cost_micro_usd=cost,
                credits_milli=credits,
                response=response,
                latency_ms=latency_ms,
                run_id=scope.run_id,
                company_id=scope.company_id,
                contact_id=scope.contact_id,
                detail=detail,
            )
            uow.commit()
        emit = log.warning if outcome is CallOutcome.ERROR else log.info
        emit(
            "provider_call",
            provider=provider,
            operation=operation,
            outcome=outcome.value,
            cost_micro_usd=cost,
            credits_milli=credits,
            latency_ms=latency_ms,
            **({"reason": reason} if reason else {}),
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
        asked: str = "",
        got: Callable[[T], str] | None = None,
        tokens: Callable[[T], tuple[str, int, int]] | None = None,
    ) -> T:
        """Cache, cap, call, record. ``found`` false makes the entry a miss (still reusable).
        ``asked`` and ``got`` say in words what was asked and what came back; they are kept on
        the ledger row for the lead page."""
        if ttl is not None:
            cached: T | None = self.lookup(
                provider, operation, request, ttl=ttl, decode=decode, asked=asked, got=got
            )
            if cached is not None:
                return cached

        self._enforce_cap(provider, operation, request, asked)

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
                # A ProviderError's message never holds a key or an address (errors.py), so it
                # is safe to log; without it a cut-off model reply looked like any failure.
                reason=str(error)[:200] if isinstance(error, ProviderError) else None,
                detail=_detail(
                    asked, str(error)[:200] if isinstance(error, ProviderError) else "failed"
                ),
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
            detail=_detail(asked, got(result) if got else ""),
            tokens=tokens(result) if tokens else None,
        )
        return result

    def _enforce_cap(
        self, provider: str, operation: str, request: Mapping[str, Any], asked: str = ""
    ) -> None:
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
                detail=_detail(asked, reason),
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


DETAIL_CHARS = 300


def _detail(asked: str, got: str = "") -> dict[str, str] | None:
    """What a call asked and what came back, in a line each, for the lead page. May name a
    person or an address, like the stored answer does, so it is erased with it."""
    if not asked and not got:
        return None
    return {"asked": asked[:DETAIL_CHARS], "got": got[:DETAIL_CHARS]}


def _quote(text: str, limit: int = 120) -> str:
    one = " ".join(text.split())
    return f'"{one[:limit]}{"…" if len(one) > limit else ""}"'


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


# --------------------------------------------------------------------------- wrapped ports


class MeteredFinder:
    def __init__(
        self, inner: EmailFinder, meter: Meter, *, ttl: timedelta | None = FINDER_TTL
    ) -> None:
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
            asked=f"{person.first_name} {person.last_name} at {domain}",
            got=lambda r: "address found" if r.email else "nothing found",
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
            asked=email,
            got=lambda r: f"{r.status.value}{f' ({r.raw_status})' if r.raw_status else ''}",
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
            self.name, "resolve", {"email": email}, ttl=self._ttl, decode=_decode_resolution,
            asked=email, got=lambda r: r.status.value,
        )  # fmt: skip
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
            asked=email,
            got=lambda t: t.result.status.value if t.result is not None else "queued",
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
            detail=_detail(email, result.status.value),
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
            asked=_quote(query)
            + (", news" if topic == "news" else "")
            + (f", last {days} days" if days else ""),
            got=lambda hits: f"{len(hits)} result{'s' if len(hits) != 1 else ''}",
        )

    def extract(self, urls: list[str], *, links: bool = False) -> list[PageText]:
        request: dict[str, object] = {"urls": sorted(urls)}
        if links:  # only when set, so earlier cached pages still match
            request["links"] = True
        return self._meter.call(
            provider=self.name,
            operation="extract",
            request=request,
            run=lambda: self._inner.extract(urls, links=links),
            encode=lambda pages: {"items": [p.model_dump(mode="json") for p in pages]},
            decode=lambda stored: [PageText.model_validate(i) for i in stored["items"]],
            found=bool,
            ttl=self._ttl,
            asked=", ".join(sorted(urls)[:3])
            + (f" +{len(urls) - 3} more" if len(urls) > 3 else ""),
            got=lambda pages: f"{len(pages)} of {len(urls)} pages read",
        )


class MeteredLeadSource:
    """A company directory or index, cached per query like a search (a directory changes
    slowly; a new run with the same brief asks the same question)."""

    def __init__(self, inner: LeadSource, meter: Meter, *, ttl: timedelta = SEARCH_TTL) -> None:
        self._inner = inner
        self._meter = meter
        self._ttl = ttl
        self.name = inner.name

    def find(self, query: SourceQuery, *, limit: int) -> list[CompanyMention]:
        return self._meter.call(
            provider=self.name,
            operation="find",
            request={**query.model_dump(mode="json"), "limit": limit},
            run=lambda: self._inner.find(query, limit=limit),
            encode=lambda found: {"items": [m.model_dump(mode="json") for m in found]},
            decode=lambda stored: [CompanyMention.model_validate(i) for i in stored["items"]],
            found=bool,
            ttl=self._ttl,
            asked=_quote(", ".join([*query.keywords, *query.regions]) or "the brief"),
            got=lambda found: f"{len(found)} companies",
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
            asked=f"{self.model}: {_quote(system, 80)}",
            got=lambda r: f"{r.input_tokens} tokens in, {r.output_tokens} out",
            tokens=lambda r: (self.model, r.input_tokens, r.output_tokens),
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
            asked=_quote(company_name),
            got=lambda entries: (
                f"{len(entries)} match{'es' if len(entries) != 1 else ''}"
                if entries
                else "no match"
            ),
        )
