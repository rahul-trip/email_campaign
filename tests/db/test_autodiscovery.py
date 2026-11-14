"""Discovery that queues itself for a campaign that says who it is after."""

from __future__ import annotations

from datetime import datetime, timedelta

from outbound.db.types import utcnow
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.entities import Campaign
from outbound.domain.enums import CompanySource, CompanyStatus, RunKind, RunStatus
from outbound.services.autodiscovery import BACKLOG, INTERVAL, AutoDiscovery
from outbound.services.runs import RunMode, RunRequest, RunService
from outbound.services.settings import SettingsService


class Clock:
    def __init__(self) -> None:
        self.at = utcnow()

    def __call__(self) -> datetime:
        return self.at


def auto(factory: UnitOfWorkFactory, ws: str, clock: Clock | None = None) -> AutoDiscovery:
    return AutoDiscovery(factory, ws, RunService(factory, ws), clock or Clock())


def campaign(
    factory: UnitOfWorkFactory, ws: str, name: str = "grids", icp: str = "grid operators"
) -> Campaign:
    with factory(ws) as uow:
        made = uow.campaigns.create(name, ["CTO"], icp_description=icp)
        uow.commit()
    return made


def queued(factory: UnitOfWorkFactory, ws: str) -> list[dict[str, object]]:
    with factory(ws) as uow:
        return [r.params or {} for r in uow.runs.recent(50) if r.status is RunStatus.QUEUED]


def test_a_campaign_that_names_its_customer_gets_a_discovery_run_queued(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    campaign(factory, ws)
    run_id = auto(factory, ws).queue_due()
    assert run_id is not None
    (params,) = queued(factory, ws)
    assert params["mode"] == RunMode.DISCOVERY.value
    assert params["campaign"] == "grids" and params["automatic"] is True
    assert params["discover"] == 10


def test_a_campaign_with_no_ideal_customer_is_left_alone(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    campaign(factory, ws, icp="  ")
    assert auto(factory, ws).queue_due() is None
    assert queued(factory, ws) == []


def test_a_campaign_is_searched_once_a_day_however_the_last_search_ended(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    campaign(factory, ws)
    clock = Clock()
    service = auto(factory, ws, clock)
    first = service.queue_due()
    assert first is not None
    with factory(ws) as uow:  # it ran and failed
        uow.runs.cancel(first)
        uow.commit()
    clock.at += INTERVAL - timedelta(minutes=1)
    assert service.queue_due() is None
    clock.at += timedelta(minutes=2)
    assert service.queue_due() is not None


def test_a_search_a_person_started_counts_as_todays_search(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    campaign(factory, ws)
    runs = RunService(factory, ws)
    done = runs.queue(RunRequest(mode=RunMode.DISCOVERY, campaign="grids"))
    with factory(ws) as uow:
        uow.runs.cancel(done.id)
        uow.commit()
    assert auto(factory, ws).queue_due() is None


def test_nothing_is_queued_while_another_run_is_waiting_or_running(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    campaign(factory, ws)
    RunService(factory, ws).queue(RunRequest())  # a person's run, still queued
    assert auto(factory, ws).queue_due() is None


def test_nothing_is_queued_while_the_campaign_has_a_backlog(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    made = campaign(factory, ws)
    with factory(ws) as uow:
        for n in range(BACKLOG):
            uow.companies.create(
                domain=f"acme{n}.example", source=CompanySource.DISCOVERY, campaign_id=made.id
            )
        uow.commit()
    assert auto(factory, ws).queue_due() is None
    with factory(ws) as uow:  # the work is done (or given up)
        for company in uow.companies.due(CompanyStatus.NEW, BACKLOG):
            uow.companies.transition(
                company.id,
                CompanyStatus.FAILED,
                expected_version=company.row_version,
                failed_stage="research",
                actor="system",
            )
        uow.commit()
    assert auto(factory, ws).queue_due() is not None


def test_it_can_be_switched_off_for_a_workspace(factory: UnitOfWorkFactory, ws: str) -> None:
    campaign(factory, ws)
    SettingsService(factory, ws).update_workspace_settings({"auto_discovery": False})
    assert auto(factory, ws).queue_due() is None


def test_one_campaign_is_searched_at_a_time(factory: UnitOfWorkFactory, ws: str) -> None:
    campaign(factory, ws, "grids")
    campaign(factory, ws, "solar", icp="solar developers")
    service = auto(factory, ws)
    assert service.queue_due() is not None
    assert service.queue_due() is None  # the first search is still waiting
    assert [p["campaign"] for p in queued(factory, ws)] == ["grids"]


def test_background_runs_do_not_hold_up_a_search(factory: UnitOfWorkFactory, ws: str) -> None:
    campaign(factory, ws)
    with factory(ws) as uow:
        uow.runs.queue(RunKind.SYNC, {"jobs": []})
        uow.commit()
    assert auto(factory, ws).queue_due() is not None
