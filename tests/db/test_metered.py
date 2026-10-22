"""The meter: cache, caps and cost records, with fake providers and a real database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import CallOutcome, CompanySource
from outbound.metering.budget import BudgetPolicy
from outbound.metering.metered import (
    Meter,
    MeteredFinder,
    MeteredLlm,
    MeteredResolver,
    MeteredSearch,
    MeteredVerifier,
    call_scope,
    request_hash,
)
from outbound.providers.errors import BudgetExceeded, ProviderError
from outbound.providers.ports import (
    FinderResult,
    LlmResult,
    PageText,
    PersonQuery,
    ResolutionResult,
    ResolutionStatus,
    ResolutionTicket,
    SearchHit,
    VerificationResult,
    VerificationStatus,
)
from outbound.providers.pricing import llm_cost

PRICES = {
    "fake:find": 1_000,
    "fake:verify": 100,
    "fake:resolve": 500,
    "fake:search": 50,
    "fake:extract": 70,
}
JANE = PersonQuery(first_name="Jane", last_name="Doe")


class FakeFinder:
    name = "fake"

    def __init__(self, email: str | None = "jane@acme.com", billed: bool = True) -> None:
        self.calls = 0
        self._email = email
        self._billed = billed

    def find(self, person: PersonQuery, domain: str) -> FinderResult:
        self.calls += 1
        return FinderResult(email=self._email, provider=self.name, billed=self._billed)


class FakeVerifier:
    name = "fake"

    def __init__(self, fail: bool = False) -> None:
        self.calls = 0
        self._fail = fail

    def verify(self, email: str) -> VerificationResult:
        self.calls += 1
        if self._fail:
            raise ProviderError(self.name, "boom", retryable=True)
        return VerificationResult(email=email, status=VerificationStatus.VALID, provider=self.name)


class FakeResolver:
    name = "fake"

    def __init__(self, immediate: bool = False) -> None:
        self.submits = 0
        self.polls = 0
        self._immediate = immediate

    def _result(self, email: str) -> ResolutionResult:
        return ResolutionResult(email=email, status=ResolutionStatus.VALID, provider=self.name)

    def submit(self, email: str) -> ResolutionTicket:
        self.submits += 1
        return ResolutionTicket(
            ref="job-1",
            email=email,
            provider=self.name,
            result=self._result(email) if self._immediate else None,
        )

    def poll(self, ticket: ResolutionTicket) -> ResolutionResult | None:
        self.polls += 1
        return self._result(ticket.email) if self.polls >= 2 else None


class FakeSearch:
    name = "fake"

    def __init__(self, hits: list[SearchHit] | None = None) -> None:
        self.searches = 0
        self.extracts = 0
        self._hits = [SearchHit(url="https://acme.com")] if hits is None else hits

    def search(
        self, query: str, *, max_results: int = 5, topic: str = "general", days: int | None = None
    ) -> list[SearchHit]:
        self.searches += 1
        return self._hits

    def extract(self, urls: list[str]) -> list[PageText]:
        self.extracts += 1
        return [PageText(url=u, text="about us") for u in urls]


def meter(
    factory: UnitOfWorkFactory,
    ws: str,
    budget: BudgetPolicy | None = None,
    clock: datetime | None = None,
) -> Meter:
    return Meter(
        factory,
        ws,
        prices=PRICES,
        budget=budget,
        clock=(lambda: clock) if clock else lambda: datetime.now(UTC),
    )


def ledger(factory: UnitOfWorkFactory, ws: str) -> list[tuple[str, CallOutcome, int]]:
    from sqlalchemy import select

    from outbound.db.models import ProviderCallRow

    with factory(ws) as uow:
        rows = uow.session.scalars(select(ProviderCallRow).order_by(ProviderCallRow.created_at))
        return [(r.operation, r.outcome, r.cost_micro_usd) for r in rows]


def new_company(factory: UnitOfWorkFactory, ws: str, domain: str = "acme.com") -> str:
    with factory(ws) as uow:
        company = uow.companies.create(domain=domain, source=CompanySource.MANUAL)
        uow.commit()
        return company.id


# ------------------------------------------------------------------ request hashing


def test_equivalent_requests_hash_the_same() -> None:
    a = request_hash("p", "find", {"email": " Jane@Acme.com ", "n": 1})
    b = request_hash("p", "find", {"n": 1, "email": "jane@acme.com"})
    assert a == b


def test_different_requests_or_operations_hash_differently() -> None:
    base = request_hash("p", "find", {"email": "a@x.com"})
    assert base != request_hash("p", "find", {"email": "b@x.com"})
    assert base != request_hash("p", "verify", {"email": "a@x.com"})
    assert base != request_hash("q", "find", {"email": "a@x.com"})


# ------------------------------------------------------------------ cache and cost


def test_a_found_address_is_billed_once_then_served_from_the_ledger(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    inner = FakeFinder()
    finder = MeteredFinder(inner, meter(factory, ws))
    first = finder.find(JANE, "acme.com")
    second = finder.find(JANE, "ACME.com")
    assert first == second
    assert inner.calls == 1
    assert ledger(factory, ws) == [
        ("find", CallOutcome.HIT, 1_000),
        ("find", CallOutcome.CACHE_HIT, 0),
    ]


def test_nothing_found_is_remembered_so_it_is_not_paid_for_twice(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    inner = FakeFinder(email=None, billed=False)
    finder = MeteredFinder(inner, meter(factory, ws))
    assert finder.find(JANE, "acme.com").email is None
    assert finder.find(JANE, "acme.com").email is None
    assert inner.calls == 1
    assert ledger(factory, ws)[0] == ("find", CallOutcome.MISS, 0)


def test_a_vendor_that_did_not_bill_costs_nothing(factory: UnitOfWorkFactory, ws: str) -> None:
    finder = MeteredFinder(FakeFinder(billed=False), meter(factory, ws))
    finder.find(JANE, "acme.com")
    assert ledger(factory, ws) == [("find", CallOutcome.HIT, 0)]


def test_an_old_answer_is_asked_again(factory: UnitOfWorkFactory, ws: str) -> None:
    inner = FakeFinder()
    finder = MeteredFinder(inner, meter(factory, ws), ttl=timedelta(seconds=-1))
    finder.find(JANE, "acme.com")
    finder.find(JANE, "acme.com")
    assert inner.calls == 2


def test_a_different_person_is_a_different_request(factory: UnitOfWorkFactory, ws: str) -> None:
    inner = FakeFinder()
    finder = MeteredFinder(inner, meter(factory, ws))
    finder.find(JANE, "acme.com")
    finder.find(PersonQuery(first_name="Joe", last_name="Bloggs"), "acme.com")
    assert inner.calls == 2


def test_the_cache_is_per_workspace(factory: UnitOfWorkFactory, ws: str, other_ws: str) -> None:
    inner = FakeFinder()
    MeteredFinder(inner, meter(factory, ws)).find(JANE, "acme.com")
    MeteredFinder(inner, meter(factory, other_ws)).find(JANE, "acme.com")
    assert inner.calls == 2


def test_a_failed_call_is_recorded_with_no_cost_and_is_not_cached(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    inner = FakeVerifier(fail=True)
    verifier = MeteredVerifier(inner, meter(factory, ws))
    for _ in range(2):
        with pytest.raises(ProviderError):
            verifier.verify("jane@acme.com")
    assert inner.calls == 2
    assert [row[1:] for row in ledger(factory, ws)] == [(CallOutcome.ERROR, 0)] * 2


def test_the_ledger_attributes_calls_to_the_run_company_and_contact(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    company_id = new_company(factory, ws)
    with call_scope(company_id=company_id):
        MeteredVerifier(FakeVerifier(), meter(factory, ws)).verify("jane@acme.com")
    with factory(ws) as uow:
        assert uow.calls.spend_on_company(company_id) == 100


# ------------------------------------------------------------------ caps


def test_a_call_that_would_pass_the_monthly_cap_is_refused_and_recorded(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    budget = BudgetPolicy(monthly_caps={"fake": 1_500})
    inner = FakeFinder()
    finder = MeteredFinder(inner, meter(factory, ws, budget))
    finder.find(JANE, "acme.com")  # 1,000 spent
    with pytest.raises(BudgetExceeded) as caught:
        finder.find(PersonQuery(first_name="Joe", last_name="Bloggs"), "acme.com")
    assert "monthly cap" in str(caught.value)
    assert inner.calls == 1
    assert ledger(factory, ws)[-1] == ("find", CallOutcome.BLOCKED_BY_CAP, 0)


def test_a_cached_answer_is_served_even_when_the_cap_is_reached(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    finder = MeteredFinder(
        FakeFinder(), meter(factory, ws, BudgetPolicy(monthly_caps={"fake": 1_000}))
    )
    finder.find(JANE, "acme.com")
    assert finder.find(JANE, "acme.com").email == "jane@acme.com"


def test_spend_from_last_month_does_not_count_against_this_months_cap(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    budget = BudgetPolicy(monthly_caps={"fake": 1_000})
    MeteredFinder(FakeFinder(), meter(factory, ws, budget)).find(JANE, "acme.com")
    next_month = datetime.now(UTC) + timedelta(days=40)
    later = MeteredFinder(FakeFinder(), meter(factory, ws, budget, clock=next_month))
    later.find(PersonQuery(first_name="Joe", last_name="Bloggs"), "acme.com")


def test_the_per_prospect_ceiling_stops_paid_calls_for_that_company_only(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    budget = BudgetPolicy(per_prospect=1_050)
    spender = new_company(factory, ws, "acme.com")
    fresh = new_company(factory, ws, "other.com")
    m = meter(factory, ws, budget)
    finder = MeteredFinder(FakeFinder(), m)
    verifier = MeteredVerifier(FakeVerifier(), m)

    with call_scope(company_id=spender):
        finder.find(JANE, "acme.com")  # 1,000
        with pytest.raises(BudgetExceeded) as caught:
            verifier.verify("jane@acme.com")  # +100 would be 1,100
        assert "per-prospect" in str(caught.value)
    with call_scope(company_id=fresh):
        verifier.verify("jane@other.com")


def test_no_company_in_scope_means_the_per_prospect_ceiling_does_not_apply(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    finder = MeteredFinder(FakeFinder(), meter(factory, ws, BudgetPolicy(per_prospect=1)))
    finder.find(JANE, "acme.com")


def test_budget_policy_reads_the_workspace_ceiling() -> None:
    policy = BudgetPolicy.from_workspace_settings({"budget_per_prospect_micro_usd": 500_000})
    assert policy.per_prospect == 500_000
    assert BudgetPolicy.from_workspace_settings({}).per_prospect is None


# ------------------------------------------------------------------ resolver


def test_an_immediate_resolution_is_billed_and_then_cached(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    inner = FakeResolver(immediate=True)
    resolver = MeteredResolver(inner, meter(factory, ws))
    first = resolver.submit("jane@acme.com")
    again = resolver.submit("jane@acme.com")
    assert first.result is not None
    assert again.result is not None
    assert inner.submits == 1


def test_an_asynchronous_resolution_is_billed_on_submit_and_remembered_when_it_finishes(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    inner = FakeResolver()
    resolver = MeteredResolver(inner, meter(factory, ws))
    ticket = resolver.submit("jane@acme.com")
    assert ticket.result is None
    assert resolver.poll(ticket) is None
    assert resolver.poll(ticket) is not None

    later = resolver.submit("jane@acme.com")
    assert later.result is not None  # no second submission, no second charge
    assert inner.submits == 1
    operations = [(op, outcome, cost) for op, outcome, cost in ledger(factory, ws)]
    assert operations[0] == ("submit", CallOutcome.HIT, 500)
    assert sum(cost for _, _, cost in operations) == 500


# ------------------------------------------------------------------ search


def test_search_and_extract_are_cached_separately(factory: UnitOfWorkFactory, ws: str) -> None:
    inner = FakeSearch()
    search = MeteredSearch(inner, meter(factory, ws))
    assert search.search("Acme energy")[0].url == "https://acme.com"
    search.search("acme energy ")
    assert inner.searches == 1
    pages = search.extract(["https://b.com", "https://a.com"])
    search.extract(["https://a.com", "https://b.com"])
    assert inner.extracts == 1
    assert {p.url for p in pages} == {"https://a.com", "https://b.com"}


def test_a_search_with_no_results_is_a_cached_miss(factory: UnitOfWorkFactory, ws: str) -> None:
    inner = FakeSearch(hits=[])
    search = MeteredSearch(inner, meter(factory, ws))
    assert search.search("nothing") == []
    assert search.search("nothing") == []
    assert inner.searches == 1
    assert ledger(factory, ws)[0][1] is CallOutcome.MISS


def test_a_news_search_is_cached_apart_from_a_general_one_and_for_only_a_week(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    inner = FakeSearch()
    start = datetime.now(UTC)
    search = MeteredSearch(inner, meter(factory, ws, clock=start))
    search.search("Acme energy")
    search.search("Acme energy", topic="news", days=180)
    search.search("Acme energy", topic="news", days=90)  # a different window is a different search
    assert inner.searches == 3
    search.search("acme energy", topic="news", days=180)
    assert inner.searches == 3  # the same news search a moment later is answered from the ledger
    # A week and a day later the news is looked up again; the general search is still cached.
    later = MeteredSearch(inner, meter(factory, ws, clock=start + timedelta(days=8)))
    later.search("Acme energy", topic="news", days=180)
    later.search("Acme energy")
    assert inner.searches == 4


# ------------------------------------------------------------------ language model


class FakeLlm:
    name = "fake-llm"
    model = "small"

    def __init__(self) -> None:
        self.calls = 0

    def complete(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LlmResult:
        self.calls += 1
        return LlmResult(
            text=f"draft {self.calls}",
            provider=self.name,
            model=self.model,
            input_tokens=2_000,
            output_tokens=500,
        )


def test_model_calls_are_priced_per_token_and_not_replayed_by_default(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    inner = FakeLlm()
    llm = MeteredLlm(inner, meter(factory, ws), prices={"small": (1_000_000, 5_000_000)})
    assert llm.complete("sys", "usr").text == "draft 1"
    assert llm.complete("sys", "usr").text == "draft 2"
    assert inner.calls == 2
    # 2,000 input tokens at $1 per million + 500 output at $5 per million = $0.0045
    assert [cost for _, _, cost in ledger(factory, ws)] == [4_500, 4_500]


def test_an_unpriced_model_is_recorded_as_free(factory: UnitOfWorkFactory, ws: str) -> None:
    MeteredLlm(FakeLlm(), meter(factory, ws), prices={}).complete("s", "u")
    assert ledger(factory, ws) == [("complete", CallOutcome.HIT, 0)]


def test_a_deterministic_task_can_opt_into_caching(factory: UnitOfWorkFactory, ws: str) -> None:
    inner = FakeLlm()
    llm = MeteredLlm(inner, meter(factory, ws), ttl=timedelta(days=30))
    assert llm.complete("classify", "hello").text == llm.complete("classify", "hello").text
    assert inner.calls == 1


def test_the_llm_cost_helper_rounds_up() -> None:
    assert llm_cost({"m": (1, 1)}, "m", 1, 0) == 1
    assert llm_cost({"m": (1_000_000, 0)}, "m", 3, 0) == 3
