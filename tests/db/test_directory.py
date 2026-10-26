"""The verified lead directory (Phase 6g): shared between customers, correctable, removable, and
never showing who contributed or looked something up."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from outbound.db.platform import PlatformUnitOfWorkFactory
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.directory import RETENTION
from outbound.domain.enums import (
    CallOutcome,
    CompanySource,
    DirectoryTarget,
    Provenance,
)
from outbound.domain.hashing import hash_value
from outbound.providers.ports import PersonQuery
from outbound.services.directory import DirectoryService
from outbound.stages.email.directory import DirectoryFinder
from tests.db.conftest import IS_POSTGRES

JANE = PersonQuery(first_name="Jane", last_name="Doe")


def contribute(
    factory: UnitOfWorkFactory, ws: str, email: str = "jane.doe@acme.com", source: str = "hunter"
) -> None:
    with factory(ws) as uow:
        uow.directory.observe_email(
            email=email,
            domain="acme.com",
            first_name="Jane",
            last_name="Doe",
            full_name="Jane Doe",
            title="CFO",
            provenance=Provenance.API_DATABASE.value,
            source=source,
            verified_by="zerobounce",
            observed_at=datetime.now(UTC),
        )
        uow.commit()


def service(platform: PlatformUnitOfWorkFactory) -> DirectoryService:
    return DirectoryService(platform, finder_price_micro_usd=24_500)


def find(factory: UnitOfWorkFactory, ws: str) -> str | None:
    return DirectoryFinder(factory, ws).find(JANE, "acme.com").email


def test_an_address_one_customer_verified_is_served_to_another_only_after_folding(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory, ws: str, other_ws: str
) -> None:
    contribute(factory, ws)
    assert find(factory, other_ws) is None  # observed, not yet applied
    assert service(platform).run()["emails"] == 1
    assert find(factory, other_ws) == "jane.doe@acme.com"
    assert find(factory, ws) == "jane.doe@acme.com"  # and to the contributor
    result = DirectoryFinder(factory, other_ws).find(JANE, "acme.com")
    assert result.billed is False and result.provider == "directory"


def test_a_hit_carries_no_contributor_and_only_a_month(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory, ws: str, other_ws: str
) -> None:
    contribute(factory, ws)
    service(platform).run()
    with factory(other_ws) as uow:
        hit = uow.directory.find_email("acme.com", "Jane", "Doe", datetime.now(UTC))
    assert hit is not None
    assert set(vars(hit)) == {"email", "source", "verified_month"}
    assert len(hit.verified_month) == 7  # YYYY-MM
    assert ws not in repr(hit)


def test_names_meet_whatever_the_case_or_spacing(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory, ws: str, other_ws: str
) -> None:
    contribute(factory, ws)
    service(platform).run()
    with factory(other_ws) as uow:
        assert uow.directory.find_email("ACME.com", " jane ", "DOE", datetime.now(UTC))


def test_a_reported_address_is_not_served_until_staff_decide(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory, ws: str, other_ws: str
) -> None:
    contribute(factory, ws)
    svc = service(platform)
    svc.run()
    with factory(other_ws) as uow:
        uow.directory.report(DirectoryTarget.EMAIL, "jane.doe@acme.com", "still_works", "left")
        uow.commit()
    assert find(factory, ws) is None  # at once, for everyone
    [flag] = svc.overview().flags
    svc.resolve(flag.id, accept=False, note="she is still there", by="staff")
    assert find(factory, ws) == "jane.doe@acme.com"  # the report was wrong: served again


def test_an_accepted_report_removes_the_address_for_good(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory, ws: str, other_ws: str
) -> None:
    contribute(factory, ws)
    svc = service(platform)
    svc.run()
    with factory(other_ws) as uow:
        uow.directory.report(DirectoryTarget.EMAIL, "jane.doe@acme.com", "email", "bounces")
        uow.commit()
    [flag] = svc.overview().flags
    svc.resolve(flag.id, accept=True, note="confirmed", by="staff")
    assert find(factory, ws) is None
    contribute(factory, ws)  # someone verifies it again: it is not learned again
    svc.run()
    assert find(factory, ws) is None
    assert svc.overview().flags == []


def test_forgetting_a_person_removes_them_and_blocks_adding_them_again(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory, ws: str, other_ws: str
) -> None:
    from outbound.services.forget import forget_email

    contribute(factory, ws)
    svc = service(platform)
    svc.run()
    with factory(other_ws) as uow:
        forget_email(uow, "Jane.Doe@acme.com")
        uow.commit()
    assert find(factory, ws) is None  # not served from the moment of the request
    with platform() as p:  # nothing observed about the address is left either
        assert p.directory.history("jane.doe@acme.com") == []
    assert svc.run()["removed"] == 1
    contribute(factory, ws)
    assert svc.run()["emails"] == 0  # never added again
    with platform() as p:
        assert (
            p.directory.figures(
                datetime(2000, 1, 1, tzinfo=UTC), datetime(2100, 1, 1, tzinfo=UTC), 0
            ).emails
            == 0
        )


def test_facts_not_confirmed_within_the_retention_window_are_deleted(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory, ws: str
) -> None:
    contribute(factory, ws)
    svc = service(platform)
    svc.run()
    late = DirectoryService(
        platform,
        finder_price_micro_usd=0,
        now=lambda: datetime.now(UTC) + RETENTION + timedelta(days=1),
    )
    assert late.run()["expired"] == 1
    assert find(factory, ws) is None


def test_a_pattern_is_served_once_observed_and_weakens_when_contradicted(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory, ws: str, other_ws: str
) -> None:
    for _ in range(2):
        with factory(ws) as uow:
            uow.directory.observe_pattern("acme.com", "first.last", "hunter", datetime.now(UTC))
            uow.commit()
    svc = service(platform)
    svc.run()
    with factory(other_ws) as uow:
        assert uow.directory.pattern("acme.com") == "first.last"
    with factory(ws) as uow:
        uow.directory.observe_pattern("acme.com", "flast", "hunter", datetime.now(UTC))
        uow.commit()
    svc.run()
    with factory(other_ws) as uow:
        assert uow.directory.pattern("acme.com") == "first.last"  # one dissent does not flip it


def test_hits_and_what_they_saved_show_in_the_figures(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory, ws: str, other_ws: str
) -> None:
    contribute(factory, ws)
    service(platform).run()
    with factory(other_ws) as uow:
        uow.calls.record(
            provider="directory",
            operation="find",
            request_hash="h" * 64,
            outcome=CallOutcome.HIT,
        )
        uow.commit()
    figures = service(platform).overview().figures
    assert figures.hits == 1 and figures.saved_micro_usd == 24_500 and figures.emails == 1


def test_a_lead_can_be_set_to_skip_the_directory(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        company = uow.companies.create(domain="acme.com", source=CompanySource.MANUAL)
        uow.companies.set_skip_directory(company.id, True, actor="operator")
        uow.commit()
    with factory(ws) as uow:
        assert uow.companies.get(company.id).skip_directory is True


@pytest.mark.skipif(not IS_POSTGRES, reason="column privileges are Postgres only")
def test_the_app_role_cannot_read_who_contributed_or_reported(engine: Engine) -> None:
    with engine.connect() as connection:
        for sql in (
            "SELECT contributor_workspace_id FROM directory_observations",
            "SELECT * FROM directory_observations",
            "SELECT reporter_workspace_id FROM directory_flags",
            "SELECT * FROM directory_flags",
            "SELECT contributor_workspace_id FROM directory_observations",
            "SELECT id FROM directory_suppressions",
        ):
            with pytest.raises(DBAPIError):
                connection.execute(text(sql))
            connection.rollback()
        assert (
            connection.execute(text("SELECT target_key, status FROM directory_flags")).all() == []
        )
        assert connection.execute(text("SELECT value_hash FROM directory_suppressions")).all() == []
    assert hash_value("x")  # hashes only are ever stored
