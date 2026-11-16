"""One campaign per workspace is active; a paused campaign's leads wait."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import CampaignStatus, CompanySource, CompanyStatus
from outbound.services.autodiscovery import AutoDiscovery
from outbound.services.runs import RunService
from outbound.services.setup import SetupService


def names(factory: UnitOfWorkFactory, ws: str) -> dict[str, CampaignStatus]:
    with factory(ws) as uow:
        return {c.name: c.status for c in uow.campaigns.all()}


def make(factory: UnitOfWorkFactory, ws: str, name: str, icp: str | None = "grid operators") -> str:
    with factory(ws) as uow:
        made = uow.campaigns.create(name, ["CTO"], icp_description=icp)
        uow.commit()
    return made.id


def test_the_first_campaign_is_active_and_a_later_one_waits(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    make(factory, ws, "first")
    make(factory, ws, "second")
    assert names(factory, ws) == {
        "first": CampaignStatus.ACTIVE,
        "second": CampaignStatus.PAUSED,
    }


def test_switching_one_on_pauses_the_other_and_two_cannot_be_active(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    make(factory, ws, "first")
    second = make(factory, ws, "second")
    with factory(ws) as uow:
        uow.campaigns.activate(second)
        uow.commit()
    assert names(factory, ws) == {"first": CampaignStatus.PAUSED, "second": CampaignStatus.ACTIVE}
    with factory(ws) as uow:
        assert uow.campaigns.active() is not None
        assert uow.campaigns.active().name == "second"  # type: ignore[union-attr]
    first = next(c.id for c in _all(factory, ws) if c.name == "first")
    from outbound.db.models import CampaignRow

    with pytest.raises(IntegrityError), factory(ws) as uow:
        uow.session.get(CampaignRow, first).status = CampaignStatus.ACTIVE  # type: ignore[union-attr]
        uow.session.flush()


def _all(factory: UnitOfWorkFactory, ws: str):  # type: ignore[no-untyped-def]
    with factory(ws) as uow:
        return uow.campaigns.all()


def lead(factory: UnitOfWorkFactory, ws: str, campaign_id: str | None, domain: str) -> str:
    with factory(ws) as uow:
        company = uow.companies.create(
            domain=domain, source=CompanySource.MANUAL, campaign_id=campaign_id
        )
        uow.commit()
    return company.id


def due_domains(factory: UnitOfWorkFactory, ws: str) -> set[str]:
    with factory(ws) as uow:
        return {c.domain for c in uow.companies.due(CompanyStatus.NEW, 50)}


def test_a_paused_campaigns_leads_are_not_due_until_it_is_switched_on(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    first = make(factory, ws, "first")
    second = make(factory, ws, "second")
    lead(factory, ws, first, "a.com")
    lead(factory, ws, second, "b.com")
    lead(factory, ws, None, "by-hand.com")  # no campaign: never held back
    assert due_domains(factory, ws) == {"a.com", "by-hand.com"}
    with factory(ws) as uow:
        assert uow.companies.any_due([CompanyStatus.NEW])
        uow.campaigns.activate(second)
        uow.commit()
    assert due_domains(factory, ws) == {"b.com", "by-hand.com"}
    with factory(ws) as uow:
        uow.campaigns.pause(second)
        uow.commit()
    assert due_domains(factory, ws) == {"by-hand.com"}


def test_auto_discovery_searches_only_for_the_active_campaign(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    make(factory, ws, "first")
    second = make(factory, ws, "second")
    service = AutoDiscovery(factory, ws, RunService(factory, ws))
    run = service.queue_due()
    assert run is not None
    with factory(ws) as uow:
        assert uow.runs.get(run).params["campaign"] == "first"  # type: ignore[index]
        uow.runs.cancel(run)
        uow.campaigns.activate(second)
        uow.commit()
    # The first campaign was searched today; the newly active one has not been.
    again = service.queue_due()
    assert again is not None
    with factory(ws) as uow:
        assert uow.runs.get(again).params["campaign"] == "second"  # type: ignore[index]


def test_the_setup_list_asks_for_the_active_campaign_to_be_ready(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    make(factory, ws, "empty", icp=None)
    ready = make(factory, ws, "ready")

    def campaign_item() -> str:
        report = SetupService(factory, ws).report()
        return next(i.status for i in report.items if i.key == "campaign")

    assert campaign_item() == "missing"  # the active one says nothing about its customer
    with factory(ws) as uow:
        uow.campaigns.activate(ready)
        uow.commit()
    assert campaign_item() == "ok"
