"""The runner and tick, with fake stages and fake paid providers over a real database."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from outbound.db.models import EventRow, ProviderCallRow, RunRow
from outbound.db.uow import UnitOfWork, UnitOfWorkFactory
from outbound.domain.actors import OPERATOR
from outbound.domain.entities import Company, CountryPolicy
from outbound.domain.enums import (
    CallOutcome,
    CompanySource,
    CompanyStatus,
    ContactSource,
    HoldReason,
    PolicyRule,
    RunStatus,
)
from outbound.providers.budget import BudgetPolicy
from outbound.providers.metered import Meter, MeteredVerifier
from outbound.providers.ports import VerificationResult, VerificationStatus
from outbound.runner.guards import Guards
from outbound.runner.runner import Outcome, Runner
from outbound.runner.tick import Tick
from outbound.stages.base import StageContext, StageResult

C = CompanyStatus


class Killed(BaseException):
    """Stands in for the process being killed: nothing in the runner may catch it."""


class FakePaidVerifier:
    name = "fake"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def verify(self, email: str) -> VerificationResult:
        self.calls.append(email)
        return VerificationResult(email=email, status=VerificationStatus.VALID, provider=self.name)


class FakeStage:
    def __init__(
        self,
        name: str,
        input_status: CompanyStatus,
        to_status: CompanyStatus,
        *,
        guard_policy: bool = False,
        action: Callable[[StageContext], StageResult | None] | None = None,
    ) -> None:
        self.name = name
        self.input_status = input_status
        self.guard_policy = guard_policy
        self._to = to_status
        self._action = action
        self.seen: list[str] = []

    def handle(self, ctx: StageContext) -> StageResult:
        self.seen.append(ctx.company.domain)
        if self._action is not None:
            custom = self._action(ctx)
            if custom is not None:
                return custom
        return StageResult(self._to)


class Clock:
    def __init__(self) -> None:
        self.moment = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, **kwargs: float) -> None:
        self.moment += timedelta(**kwargs)


def make_runner(
    factory: UnitOfWorkFactory,
    ws: str,
    stages: list[FakeStage],
    *,
    budget: BudgetPolicy | None = None,
    clock: Clock | None = None,
    max_attempts: int = 3,
) -> Runner:
    return Runner(
        factory,
        ws,
        stages,
        Guards(budget),
        now=clock or Clock(),
        max_attempts=max_attempts,
    )


def research_runner(
    factory: UnitOfWorkFactory,
    ws: str,
    action: Callable[[StageContext], StageResult | None],
) -> Runner:
    stage = FakeStage("research", C.NEW, C.RESEARCHED, action=action)
    return make_runner(factory, ws, [stage])


def add_company(
    factory: UnitOfWorkFactory,
    ws: str,
    domain: str,
    *,
    status: CompanyStatus = C.NEW,
    country: str | None = "GB",
    priority: int = 5,
) -> str:
    with factory(ws) as uow:
        company = uow.companies.create(
            domain=domain, source=CompanySource.MANUAL, country_code=country, priority=priority
        )
        path = {
            C.NEW: [],
            C.RESEARCHED: [C.RESEARCHED],
            C.QUALIFIED: [C.RESEARCHED, C.QUALIFIED],
            C.CONTACTS_FOUND: [C.RESEARCHED, C.QUALIFIED, C.CONTACTS_FOUND],
            C.APPROVED: [
                C.RESEARCHED,
                C.QUALIFIED,
                C.CONTACTS_FOUND,
                C.EMAIL_READY,
                C.COPY_READY,
                C.APPROVED,
            ],
        }[status]
        version = company.row_version
        for step in path:
            version = uow.companies.transition(
                company.id, step, expected_version=version
            ).row_version
        uow.commit()
        return company.id


def status_of(factory: UnitOfWorkFactory, ws: str, company_id: str) -> CompanyStatus:
    with factory(ws) as uow:
        return uow.companies.get(company_id).status


def company(factory: UnitOfWorkFactory, ws: str, company_id: str) -> Company:
    with factory(ws) as uow:
        return uow.companies.get(company_id)


def events_of(factory: UnitOfWorkFactory, ws: str, company_id: str) -> list[str]:
    with factory(ws) as uow:
        return [e.type for e in uow.events.for_entity(_COMPANY, company_id)]


from outbound.domain.enums import EntityType  # noqa: E402

_COMPANY = EntityType.COMPANY

PIPELINE = [
    ("research", C.NEW, C.RESEARCHED),
    ("gate", C.RESEARCHED, C.QUALIFIED),
    ("contacts", C.QUALIFIED, C.CONTACTS_FOUND),
]


def three_stages() -> list[FakeStage]:
    return [
        FakeStage(name, source, target, guard_policy=name == "contacts")
        for name, source, target in PIPELINE
    ]


def seed_policy(factory: UnitOfWorkFactory, ws: str, code: str, rule: PolicyRule) -> None:
    with factory(ws) as uow:
        uow.policies.add_if_missing(CountryPolicy(code, rule))
        uow.commit()


# ------------------------------------------------------------------ happy path


def test_a_lead_moves_through_every_stage_in_one_run(factory: UnitOfWorkFactory, ws: str) -> None:
    cid = add_company(factory, ws, "acme.com")
    seed_policy(factory, ws, "GB", PolicyRule.ALLOW)
    report = make_runner(factory, ws, three_stages()).run_pipeline()
    assert status_of(factory, ws, cid) is C.CONTACTS_FOUND
    assert [report.count(name, Outcome.ADVANCED) for name, _, _ in PIPELINE] == [1, 1, 1]
    assert report.status is RunStatus.SUCCEEDED


def test_every_move_is_logged_by_the_runner(factory: UnitOfWorkFactory, ws: str) -> None:
    cid = add_company(factory, ws, "acme.com")
    seed_policy(factory, ws, "GB", PolicyRule.ALLOW)
    make_runner(factory, ws, three_stages()).run_pipeline()
    assert events_of(factory, ws, cid).count("status_changed") == 3


def test_priority_decides_the_order_within_a_stage(factory: UnitOfWorkFactory, ws: str) -> None:
    add_company(factory, ws, "low.com", priority=9)
    add_company(factory, ws, "high.com", priority=1)
    stage = FakeStage("research", C.NEW, C.RESEARCHED)
    make_runner(factory, ws, [stage]).run_pipeline()
    assert stage.seen == ["high.com", "low.com"]


def test_the_limit_caps_how_many_leads_a_stage_takes(factory: UnitOfWorkFactory, ws: str) -> None:
    for i in range(5):
        add_company(factory, ws, f"c{i}.com")
    stage = FakeStage("research", C.NEW, C.RESEARCHED)
    make_runner(factory, ws, [stage]).run_pipeline(limit=2)
    assert len(stage.seen) == 2


def test_only_runs_the_named_stages(factory: UnitOfWorkFactory, ws: str) -> None:
    cid = add_company(factory, ws, "acme.com")
    stages = three_stages()
    make_runner(factory, ws, stages).run_pipeline(only={"gate"})
    assert status_of(factory, ws, cid) is C.NEW
    assert stages[0].seen == []


def test_stage_updates_and_child_rows_are_written_with_the_move(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = add_company(factory, ws, "acme.com")

    def action(ctx: StageContext) -> StageResult:
        def write(uow: UnitOfWork) -> None:
            uow.contacts.add(ctx.company.id, rank=1, source=ContactSource.SITE, full_name="Jane")

        return StageResult(
            C.RESEARCHED,
            company_updates={"fit_score": 77, "fit_reason": "good fit"},
            write=write,
            reason="researched",
        )

    make_runner(
        factory, ws, [FakeStage("research", C.NEW, C.RESEARCHED, action=action)]
    ).run_pipeline()
    after = company(factory, ws, cid)
    assert (after.status, after.fit_score) == (C.RESEARCHED, 77)
    with factory(ws) as uow:
        assert [c.full_name for c in uow.contacts.for_company(cid)] == ["Jane"]


def test_a_stage_can_hold_a_lead_with_a_reason_and_a_wake_time(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = add_company(factory, ws, "acme.com", status=C.CONTACTS_FOUND)
    clock = Clock()
    wake = clock.moment + timedelta(hours=24)
    stage = FakeStage(
        "email",
        C.CONTACTS_FOUND,
        C.HELD,
        action=lambda ctx: StageResult(
            C.HELD, hold_reason=HoldReason.CATCH_ALL_RESOLVING, next_action_at=wake
        ),
    )
    report = make_runner(factory, ws, [stage], clock=clock).run_pipeline()
    held = company(factory, ws, cid)
    assert (held.status, held.hold_reason, held.next_action_at) == (
        C.HELD,
        HoldReason.CATCH_ALL_RESOLVING,
        wake,
    )
    assert report.count("email", Outcome.HELD) == 1


def test_a_lead_scheduled_for_later_is_left_alone_until_then(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = add_company(factory, ws, "acme.com")
    clock = Clock()
    with factory(ws) as uow:
        uow.companies.update_fields(
            cid,
            {"next_action_at": clock.moment + timedelta(hours=2)},
            actor=OPERATOR,
            expected_version=uow.companies.get(cid).row_version,
        )
        uow.commit()
    stage = FakeStage("research", C.NEW, C.RESEARCHED)
    runner = make_runner(factory, ws, [stage], clock=clock)
    runner.run_pipeline()
    assert stage.seen == []
    clock.advance(hours=3)
    runner.run_pipeline()
    assert stage.seen == ["acme.com"]


# ------------------------------------------------------------------ failures


def boom(ctx: StageContext) -> StageResult:
    raise RuntimeError("vendor exploded")


def test_a_failing_lead_is_marked_failed_and_the_run_carries_on(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    bad = add_company(factory, ws, "bad.com", priority=1)
    good = add_company(factory, ws, "good.com", priority=2)

    def action(ctx: StageContext) -> StageResult | None:
        return boom(ctx) if ctx.company.domain == "bad.com" else None

    stage = FakeStage("research", C.NEW, C.RESEARCHED, action=action)
    report = make_runner(factory, ws, [stage]).run_pipeline()

    failed = company(factory, ws, bad)
    assert (failed.status, failed.failed_stage, failed.attempts) == (C.FAILED, "research", 1)
    assert failed.last_error == "RuntimeError: vendor exploded"
    assert status_of(factory, ws, good) is C.RESEARCHED
    assert report.count("research", Outcome.FAILED) == 1
    assert report.status is RunStatus.SUCCEEDED


def test_an_illegal_result_from_a_stage_fails_that_lead_not_the_run(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = add_company(factory, ws, "acme.com")
    stage = FakeStage("research", C.NEW, C.APPROVED)  # NEW -> APPROVED is not a legal move
    make_runner(factory, ws, [stage]).run_pipeline()
    failed = company(factory, ws, cid)
    assert failed.status is C.FAILED
    assert "cannot move" in (failed.last_error or "")


def test_a_hold_without_a_reason_is_a_failure_of_the_stage(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = add_company(factory, ws, "acme.com", status=C.CONTACTS_FOUND)
    stage = FakeStage("email", C.CONTACTS_FOUND, C.HELD)
    make_runner(factory, ws, [stage]).run_pipeline()
    assert status_of(factory, ws, cid) is C.FAILED


def test_a_stage_that_cannot_fail_a_lead_defers_it_instead(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = add_company(factory, ws, "acme.com", status=C.APPROVED)
    clock = Clock()
    stage = FakeStage("deliver", C.APPROVED, C.IN_SEQUENCE, action=boom)
    report = make_runner(factory, ws, [stage], clock=clock).run_pipeline()
    after = company(factory, ws, cid)
    assert after.status is C.APPROVED
    assert after.next_action_at == clock.moment + timedelta(hours=1)
    assert "deferred" in events_of(factory, ws, cid)
    assert report.count("deliver", Outcome.DEFERRED) == 1


def test_an_operator_edit_during_the_stage_wins_and_the_lead_is_tried_again(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = add_company(factory, ws, "acme.com")

    def action(ctx: StageContext) -> StageResult | None:
        with factory(ws) as uow:  # the operator edits the lead while the stage is working
            uow.companies.update_fields(
                cid, {"name": "Acme Ltd"}, actor=OPERATOR, expected_version=ctx.company.row_version
            )
            uow.commit()
        return None

    stage = FakeStage("research", C.NEW, C.RESEARCHED, action=action)
    runner = make_runner(factory, ws, [stage])
    report = runner.run_pipeline()
    assert status_of(factory, ws, cid) is C.NEW
    assert report.count("research", Outcome.SKIPPED) == 1
    assert company(factory, ws, cid).name == "Acme Ltd"


# ------------------------------------------------------------------ retries


def test_a_failed_lead_waits_then_goes_back_to_the_stage_that_failed(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = add_company(factory, ws, "acme.com")
    clock = Clock()
    flaky = {"fail": True}

    def action(ctx: StageContext) -> StageResult | None:
        return boom(ctx) if flaky["fail"] else None

    runner = make_runner(
        factory, ws, [FakeStage("research", C.NEW, C.RESEARCHED, action=action)], clock=clock
    )
    runner.run_pipeline()
    assert runner.retry_failed() == 0  # still backing off
    clock.advance(minutes=16)
    assert runner.retry_failed() == 1
    assert status_of(factory, ws, cid) is C.NEW

    flaky["fail"] = False
    runner.run_pipeline()
    assert status_of(factory, ws, cid) is C.RESEARCHED


def test_the_wait_grows_with_each_failure_and_attempts_run_out(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = add_company(factory, ws, "acme.com")
    clock = Clock()
    runner = make_runner(
        factory,
        ws,
        [FakeStage("research", C.NEW, C.RESEARCHED, action=boom)],
        clock=clock,
        max_attempts=2,
    )
    runner.run_pipeline()
    first_wait = company(factory, ws, cid).next_action_at
    assert first_wait == clock.moment + timedelta(minutes=15)

    clock.advance(minutes=16)
    runner.retry_failed()
    runner.run_pipeline()
    second_wait = company(factory, ws, cid).next_action_at
    assert second_wait == clock.moment + timedelta(minutes=30)

    clock.advance(hours=2)
    assert runner.retry_failed() == 0  # two attempts used
    assert status_of(factory, ws, cid) is C.FAILED


# ------------------------------------------------------------------ guards


def test_a_suppressed_domain_is_never_handed_to_a_stage(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    from outbound.domain.enums import SuppressionKind, SuppressionReason

    cid = add_company(factory, ws, "optout.com")
    with factory(ws) as uow:
        uow.suppressions.add(SuppressionKind.DOMAIN, "optout.com", SuppressionReason.OPT_OUT)
        uow.commit()
    stage = FakeStage("research", C.NEW, C.RESEARCHED)
    report = make_runner(factory, ws, [stage]).run_pipeline()
    assert stage.seen == []
    assert status_of(factory, ws, cid) is C.SUPPRESSED
    assert report.count("research", Outcome.SUPPRESSED) == 1


def test_a_country_that_forbids_cold_email_stops_a_lead_before_a_later_stage(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = add_company(factory, ws, "acme.de", status=C.QUALIFIED, country="DE")
    seed_policy(factory, ws, "DE", PolicyRule.BLOCK)
    stage = FakeStage("contacts", C.QUALIFIED, C.CONTACTS_FOUND, guard_policy=True)
    make_runner(factory, ws, [stage]).run_pipeline()
    assert stage.seen == []
    assert status_of(factory, ws, cid) is C.SUPPRESSED


def test_a_policy_that_now_needs_a_person_holds_the_lead_when_a_hold_is_possible(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = add_company(factory, ws, "acme.com", status=C.CONTACTS_FOUND, country=None)
    stage = FakeStage("email", C.CONTACTS_FOUND, C.EMAIL_READY, guard_policy=True)
    make_runner(factory, ws, [stage]).run_pipeline()
    held = company(factory, ws, cid)
    assert (held.status, held.hold_reason) == (C.HELD, HoldReason.COUNTRY_UNKNOWN)
    assert stage.seen == []


def test_a_hold_that_the_lifecycle_does_not_allow_defers_the_lead(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = add_company(factory, ws, "acme.com", status=C.QUALIFIED, country=None)
    stage = FakeStage("contacts", C.QUALIFIED, C.CONTACTS_FOUND, guard_policy=True)
    report = make_runner(factory, ws, [stage]).run_pipeline()
    assert status_of(factory, ws, cid) is C.QUALIFIED
    assert report.count("contacts", Outcome.DEFERRED) == 1


def test_a_lead_over_its_budget_gets_no_more_paid_work(factory: UnitOfWorkFactory, ws: str) -> None:
    cid = add_company(factory, ws, "acme.com")
    with factory(ws) as uow:
        uow.calls.record(
            provider="fake",
            operation="find",
            request_hash="h",
            outcome=CallOutcome.HIT,
            cost_micro_usd=500_000,
            company_id=cid,
        )
        uow.commit()
    stage = FakeStage("research", C.NEW, C.RESEARCHED)
    make_runner(factory, ws, [stage], budget=BudgetPolicy(per_prospect=500_000)).run_pipeline()
    failed = company(factory, ws, cid)
    assert stage.seen == []
    assert (failed.status, failed.failed_stage) == (C.FAILED, "research")
    assert "budget" in (failed.last_error or "")


def test_a_budget_error_raised_inside_a_stage_fails_the_lead_with_its_message(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = add_company(factory, ws, "acme.com")
    meter = Meter(
        factory, ws, prices={"fake:verify": 100}, budget=BudgetPolicy(monthly_caps={"fake": 0})
    )
    verifier = MeteredVerifier(FakePaidVerifier(), meter)

    def action(ctx: StageContext) -> StageResult | None:
        verifier.verify("jane@acme.com")
        return None

    make_runner(
        factory, ws, [FakeStage("research", C.NEW, C.RESEARCHED, action=action)]
    ).run_pipeline()
    failed = company(factory, ws, cid)
    assert failed.status is C.FAILED
    assert "monthly cap" in (failed.last_error or "")


# ------------------------------------------------------------------ cost and runs


def test_paid_calls_inside_a_stage_are_attributed_to_the_run_and_the_company(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = add_company(factory, ws, "acme.com")
    verifier = MeteredVerifier(FakePaidVerifier(), Meter(factory, ws, prices={"fake:verify": 250}))

    def action(ctx: StageContext) -> StageResult | None:
        verifier.verify("jane@acme.com")
        return None

    report = make_runner(
        factory, ws, [FakeStage("research", C.NEW, C.RESEARCHED, action=action)]
    ).run_pipeline()
    with factory(ws) as uow:
        assert uow.calls.spend_on_company(cid) == 250
        run = uow.session.get(RunRow, report.run_id)
        assert run is not None
        assert (run.status, run.cost_micro_usd, run.counts) == (
            RunStatus.SUCCEEDED,
            250,
            {"research": {"advanced": 1}},
        )
    assert report.cost_micro_usd == 250


def test_killed_after_the_third_lead_the_rerun_finishes_without_repeating_a_paid_call(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    domains = [f"c{i}.com" for i in range(6)]
    ids = [add_company(factory, ws, d, priority=i) for i, d in enumerate(domains)]
    provider = FakePaidVerifier()
    verifier = MeteredVerifier(provider, Meter(factory, ws, prices={"fake:verify": 100}))
    kill_at = {"domain": "c3.com"}

    def action(ctx: StageContext) -> StageResult | None:
        verifier.verify(f"jane@{ctx.company.domain}")  # the paid call, recorded at once
        if ctx.company.domain == kill_at["domain"]:
            raise Killed  # the process dies after paying but before the result is written
        return None

    def build() -> Runner:
        return make_runner(factory, ws, [FakeStage("research", C.NEW, C.RESEARCHED, action=action)])

    with pytest.raises(Killed):
        build().run_pipeline()
    assert [status_of(factory, ws, i) for i in ids] == [C.RESEARCHED] * 3 + [C.NEW] * 3
    with factory(ws) as uow:
        interrupted = uow.session.scalars(select(RunRow)).one()
        assert interrupted.status is RunStatus.FAILED

    kill_at["domain"] = "never"
    build().run_pipeline()

    assert [status_of(factory, ws, i) for i in ids] == [C.RESEARCHED] * 6
    assert sorted(provider.calls) == sorted(f"jane@{d}" for d in domains)  # each paid once
    with factory(ws) as uow:
        outcomes = [r.outcome for r in uow.session.scalars(select(ProviderCallRow))]
    assert outcomes.count(CallOutcome.HIT) == 6
    assert outcomes.count(CallOutcome.CACHE_HIT) == 1  # lead 4, paid before the kill


def test_an_unfinished_run_is_not_left_marked_as_running(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    add_company(factory, ws, "acme.com")
    stage = FakeStage(
        "research", C.NEW, C.RESEARCHED, action=lambda ctx: (_ for _ in ()).throw(Killed())
    )
    with pytest.raises(Killed):
        make_runner(factory, ws, [stage]).run_pipeline()
    with factory(ws) as uow:
        assert [r.status for r in uow.session.scalars(select(RunRow))] == [RunStatus.FAILED]


# ------------------------------------------------------------------ tick


class FakeJob:
    def __init__(self, name: str, *, fail: bool = False) -> None:
        self.name = name
        self.fail = fail
        self.ran = 0

    def run(self) -> dict[str, int]:
        self.ran += 1
        if self.fail:
            raise RuntimeError("mailbox down")
        return {"matched": 2}


def test_a_tick_retries_runs_jobs_then_runs_the_pipeline(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    failed = add_company(factory, ws, "retry.com", priority=1)
    fresh = add_company(factory, ws, "fresh.com", priority=2)
    clock = Clock()
    flaky = {"fail": True}

    def action(ctx: StageContext) -> StageResult | None:
        if flaky["fail"] and ctx.company.domain == "retry.com":
            raise RuntimeError("first time unlucky")
        return None

    runner = make_runner(
        factory, ws, [FakeStage("research", C.NEW, C.RESEARCHED, action=action)], clock=clock
    )
    runner.run_pipeline()
    assert status_of(factory, ws, failed) is C.FAILED
    clock.advance(minutes=20)
    flaky["fail"] = False

    job = FakeJob("sent_sync")
    report = Tick(factory, ws, runner, [job]).run()

    assert report.retried == 1
    assert report.jobs == {"sent_sync": {"matched": 2}}
    assert job.ran == 1
    assert status_of(factory, ws, failed) is C.RESEARCHED
    assert status_of(factory, ws, fresh) is C.RESEARCHED
    assert report.pipeline is not None


def test_one_broken_job_does_not_stop_the_others_or_the_pipeline(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = add_company(factory, ws, "acme.com")
    runner = make_runner(factory, ws, [FakeStage("research", C.NEW, C.RESEARCHED)])
    broken, healthy = FakeJob("inbox", fail=True), FakeJob("sent_sync")
    report = Tick(factory, ws, runner, [broken, healthy]).run()
    assert report.jobs == {"inbox": {"failed": 1}, "sent_sync": {"matched": 2}}
    assert status_of(factory, ws, cid) is C.RESEARCHED
    with factory(ws) as uow:
        sync_runs = [r for r in uow.session.scalars(select(RunRow)) if r.kind.value == "sync"]
        assert [r.status for r in sync_runs] == [RunStatus.FAILED]


def test_a_tick_with_nothing_to_do_is_quiet(factory: UnitOfWorkFactory, ws: str) -> None:
    runner = make_runner(factory, ws, three_stages())
    report = Tick(factory, ws, runner).run()
    assert (report.retried, report.jobs) == (0, {})
    assert report.pipeline is not None
    with factory(ws) as uow:
        assert uow.session.scalars(select(EventRow)).first() is None
