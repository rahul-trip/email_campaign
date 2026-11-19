"""The two read-only queries the timing report stands on (scripts/lead_timings.py)."""

from __future__ import annotations

from datetime import timedelta

from outbound.db.types import utcnow
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import CallOutcome, CompanySource, CompanyStatus, EntityType


def test_the_call_latencies_and_status_changes_are_read_for_the_period(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        company = uow.companies.create(domain="acme.com", source=CompanySource.MANUAL)
        uow.companies.transition(
            company.id, CompanyStatus.RESEARCHED, expected_version=company.row_version
        )
        uow.calls.record(
            provider="tavily",
            operation="extract",
            request_hash="h1",
            outcome=CallOutcome.HIT,
            latency_ms=1200,
        )
        uow.calls.record(
            provider="tavily",
            operation="extract",
            request_hash="h2",
            outcome=CallOutcome.HIT,
            latency_ms=None,  # a cache hit has no latency
        )
        uow.commit()
    since = utcnow() - timedelta(hours=1)
    with factory(ws) as uow:
        assert uow.calls.latencies_since(since) == [("tavily", "extract", 1200)]
        changes = uow.events.status_changes_since(EntityType.COMPANY, since)
        assert [(status) for _, status, _ in changes] == ["researched"]
        assert uow.calls.latencies_since(utcnow() + timedelta(hours=1)) == []
