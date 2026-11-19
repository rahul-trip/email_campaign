"""Each lead can go through the stages back to back, ending where a stage-by-stage run would."""

from __future__ import annotations

from collections.abc import Callable

from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import CompanyStatus, HoldReason
from outbound.metering.budget import BudgetPolicy
from outbound.runner.guards import Guards
from outbound.runner.runner import Runner
from outbound.stages.base import StageContext, StageResult
from tests.db.test_runner import FakeStage, add_company, company

C = CompanyStatus
CHAIN = [
    ("research", C.NEW, C.RESEARCHED),
    ("gate", C.RESEARCHED, C.QUALIFIED),
    ("contacts", C.QUALIFIED, C.CONTACTS_FOUND),
    ("email", C.CONTACTS_FOUND, C.EMAIL_READY),
    ("copy", C.EMAIL_READY, C.COPY_READY),
]


def stages(
    actions: dict[str, Callable[[StageContext], StageResult | None]] | None = None,
) -> list[FakeStage]:
    actions = actions or {}
    return [
        FakeStage(name, source, target, spends=False, action=actions.get(name))
        for name, source, target in CHAIN
    ]


def runner(
    factory: UnitOfWorkFactory,
    ws: str,
    chain: list[FakeStage],
    *,
    flow: bool = True,
    concurrency: int = 1,
) -> Runner:
    return Runner(
        factory,
        ws,
        chain,
        Guards(BudgetPolicy()),
        lead_flow=flow,
        lead_concurrency=concurrency,
    )


def test_a_lead_goes_from_new_to_a_draft_in_one_pass(factory: UnitOfWorkFactory, ws: str) -> None:
    ids = [add_company(factory, ws, f"lead{i}.com") for i in range(3)]
    report = runner(factory, ws, stages(), concurrency=3).run_pipeline()
    assert all(company(factory, ws, i).status is C.COPY_READY for i in ids)
    assert {name: report.counts[name]["advanced"] for name, *_ in CHAIN} == {
        n: 3 for n, *_ in CHAIN
    }


def test_it_ends_where_a_stage_by_stage_run_ends(factory: UnitOfWorkFactory, ws: str) -> None:
    def hold(ctx: StageContext) -> StageResult:
        return StageResult(C.HELD, hold_reason=HoldReason.NEEDS_OPERATOR)

    def disqualify(ctx: StageContext) -> StageResult:
        return StageResult(C.DISQUALIFIED)

    def actions(
        domain_for: dict[str, str],
    ) -> dict[str, Callable[[StageContext], StageResult | None]]:
        return {
            "gate": lambda ctx: (
                disqualify(ctx) if ctx.company.domain == domain_for["out"] else None
            ),
            "contacts": lambda ctx: hold(ctx) if ctx.company.domain == domain_for["hold"] else None,
        }

    final: dict[bool, dict[str, CompanyStatus]] = {}
    for flow in (False, True):
        tag = "flow" if flow else "stages"  # domains are stored in lower case
        names = {"out": f"out-{tag}.com", "hold": f"hold-{tag}.com", "ok": f"ok-{tag}.com"}
        ids = {key: add_company(factory, ws, domain) for key, domain in names.items()}
        runner(factory, ws, stages(actions(names)), flow=flow, concurrency=2).run_pipeline()
        final[flow] = {key: company(factory, ws, i).status for key, i in ids.items()}
    assert (
        final[True] == final[False] == {"out": C.DISQUALIFIED, "hold": C.HELD, "ok": C.COPY_READY}
    )


def test_a_lead_that_stops_is_not_counted_at_the_stages_it_never_reached(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    add_company(factory, ws, "out.com")
    chain = stages({"gate": lambda ctx: StageResult(C.DISQUALIFIED)})
    report = runner(factory, ws, chain).run_pipeline()
    assert report.counts["gate"]["advanced"] == 1
    assert dict(report.counts["contacts"]) == {} and dict(report.counts["copy"]) == {}


def test_leads_furthest_along_go_first(factory: UnitOfWorkFactory, ws: str) -> None:
    add_company(factory, ws, "new.com")
    add_company(factory, ws, "nearly.com", status=C.EMAIL_READY)
    order: list[str] = []

    def note(ctx: StageContext) -> None:
        order.append(f"{ctx.company.domain}")

    chain = stages({name: note for name, *_ in CHAIN})
    runner(factory, ws, chain).run_pipeline()
    assert order[0] == "nearly.com"  # its draft does not wait behind the new lead's research


def test_only_still_runs_one_stage(factory: UnitOfWorkFactory, ws: str) -> None:
    lead = add_company(factory, ws, "one.com")
    runner(factory, ws, stages()).run_pipeline(only={"research"})
    assert company(factory, ws, lead).status is C.RESEARCHED


def test_a_one_at_a_time_stage_runs_as_its_own_pass_after_the_flow(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    new = add_company(factory, ws, "new.com")
    approved = add_company(factory, ws, "approved.com", status=C.APPROVED)
    deliver = FakeStage("deliver", C.APPROVED, C.IN_SEQUENCE, spends=False)
    deliver.parallel = False  # type: ignore[attr-defined]
    report = runner(factory, ws, [*stages(), deliver], concurrency=2).run_pipeline()
    assert company(factory, ws, new).status is C.COPY_READY
    assert company(factory, ws, approved).status is C.IN_SEQUENCE
    assert report.counts["deliver"]["advanced"] == 1
