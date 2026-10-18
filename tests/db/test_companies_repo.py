from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from outbound.db.errors import ConcurrencyConflict, NotFound
from outbound.db.types import utcnow
from outbound.db.uow import UnitOfWork, UnitOfWorkFactory
from outbound.domain.actors import OPERATOR, SYSTEM, provider
from outbound.domain.entities import Company
from outbound.domain.enums import CompanySource, CompanyStatus, EntityType, HoldReason
from outbound.domain.state_machines import IllegalTransition

S = CompanyStatus


def new_company(uow: UnitOfWork, domain: str = "acme.com", **kwargs: object) -> Company:
    kwargs.setdefault("source", CompanySource.MANUAL)
    return uow.companies.create(domain=domain, **kwargs)  # type: ignore[arg-type]


def event_types(uow: UnitOfWork, company_id: str) -> list[str]:
    return [e.type for e in uow.events.for_entity(EntityType.COMPANY, company_id)]


def test_create_lowercases_the_domain_and_logs_an_event(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        company = new_company(uow, "ACME.com", country_code="gb")
        uow.commit()
        assert (company.domain, company.country_code, company.status) == ("acme.com", "GB", S.NEW)
        assert company.row_version == 1
        assert event_types(uow, company.id) == ["created"]


def test_a_company_can_be_found_by_domain_and_listed(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        created = new_company(uow)
        new_company(uow, "beta.io")
        uow.commit()
        assert uow.companies.by_domain("ACME.com") == created
        assert uow.companies.by_domain("nope.com") is None
        assert uow.companies.known_domains() == {"acme.com", "beta.io"}


def test_one_company_per_domain_per_workspace(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        new_company(uow)
        with pytest.raises(IntegrityError):
            new_company(uow)


def test_the_same_domain_may_exist_in_two_workspaces(
    factory: UnitOfWorkFactory, ws: str, other_ws: str
) -> None:
    with factory(ws) as uow:
        new_company(uow)
        uow.commit()
    with factory(other_ws) as uow:
        new_company(uow)
        uow.commit()


# ------------------------------------------------------------------ isolation


def test_a_workspace_cannot_see_anothers_companies(
    factory: UnitOfWorkFactory, ws: str, other_ws: str
) -> None:
    with factory(ws) as uow:
        company = new_company(uow)
        uow.commit()
    with factory(other_ws) as uow:
        with pytest.raises(NotFound):
            uow.companies.get(company.id)
        assert uow.companies.by_domain("acme.com") is None
        assert uow.companies.known_domains() == set()
        assert uow.companies.due(S.NEW, 10) == []
        assert uow.companies.count_by_status() == {}


def test_a_workspace_cannot_change_anothers_company(
    factory: UnitOfWorkFactory, ws: str, other_ws: str
) -> None:
    with factory(ws) as uow:
        company = new_company(uow)
        uow.commit()
    with factory(other_ws) as uow, pytest.raises(NotFound):
        uow.companies.transition(company.id, S.RESEARCHED, expected_version=company.row_version)


# ------------------------------------------------------------------ transitions


def test_a_legal_transition_updates_the_row_and_logs_it(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        company = new_company(uow)
        moved = uow.companies.transition(
            company.id,
            S.RESEARCHED,
            expected_version=company.row_version,
            actor=SYSTEM,
            reason="ok",
        )
        uow.commit()
        assert moved.status is S.RESEARCHED
        assert moved.row_version == company.row_version + 1
        (_, change) = uow.events.for_entity(EntityType.COMPANY, company.id)
        assert change.type == "status_changed"
        assert change.data == {"from": "new", "to": "researched", "reason": "ok"}


def test_an_illegal_transition_is_refused_and_changes_nothing(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        company = new_company(uow)
        with pytest.raises(IllegalTransition):
            uow.companies.transition(company.id, S.APPROVED, expected_version=company.row_version)
        assert uow.companies.get(company.id).status is S.NEW
        assert event_types(uow, company.id) == ["created"]


def test_a_hold_needs_a_reason_and_releasing_it_clears_the_reason(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        company = new_company(uow)
        company = uow.companies.transition(
            company.id, S.RESEARCHED, expected_version=company.row_version
        )
        with pytest.raises(ValueError, match="hold_reason"):
            uow.companies.transition(company.id, S.HELD, expected_version=company.row_version)
        held = uow.companies.transition(
            company.id,
            S.HELD,
            expected_version=company.row_version,
            hold_reason=HoldReason.COUNTRY_UNKNOWN,
        )
        assert held.hold_reason is HoldReason.COUNTRY_UNKNOWN
        released = uow.companies.transition(
            company.id, S.RESEARCHED, expected_version=held.row_version
        )
        assert released.hold_reason is None


def test_a_failure_records_stage_and_error_and_a_retry_clears_them(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        company = new_company(uow)
        with pytest.raises(ValueError, match="failed_stage"):
            uow.companies.transition(company.id, S.FAILED, expected_version=company.row_version)
        failed = uow.companies.transition(
            company.id,
            S.FAILED,
            expected_version=company.row_version,
            failed_stage="research",
            last_error="tavily timed out",
        )
        assert (failed.failed_stage, failed.last_error, failed.attempts) == (
            "research",
            "tavily timed out",
            1,
        )
        retried = uow.companies.transition(company.id, S.NEW, expected_version=failed.row_version)
        assert (retried.failed_stage, retried.last_error, retried.attempts) == (None, None, 1)


def test_a_transition_can_schedule_the_next_action(factory: UnitOfWorkFactory, ws: str) -> None:
    when = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
    with factory(ws) as uow:
        company = new_company(uow)
        scheduled = uow.companies.transition(
            company.id, S.RESEARCHED, expected_version=company.row_version, next_action_at=when
        )
        assert scheduled.next_action_at == when
        kept = uow.companies.transition(
            company.id, S.QUALIFIED, expected_version=scheduled.row_version
        )
        assert kept.next_action_at == when  # not passed, so left alone
        cleared = uow.companies.transition(
            company.id, S.CONTACTS_FOUND, expected_version=kept.row_version, next_action_at=None
        )
        assert cleared.next_action_at is None


# ------------------------------------------------------------------ concurrency


def test_a_stale_expected_version_is_refused(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        company = new_company(uow)
        uow.companies.transition(company.id, S.RESEARCHED, expected_version=company.row_version)
        with pytest.raises(ConcurrencyConflict):
            uow.companies.transition(company.id, S.QUALIFIED, expected_version=company.row_version)


def test_two_sessions_racing_cannot_both_win(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as setup:
        company = new_company(setup)
        setup.commit()
    with factory(ws) as first, factory(ws) as second:
        seen_by_first = first.companies.get(company.id)
        seen_by_second = second.companies.get(company.id)
        first.companies.transition(
            company.id, S.RESEARCHED, expected_version=seen_by_first.row_version
        )
        first.commit()
        with pytest.raises(ConcurrencyConflict):
            second.companies.transition(
                company.id, S.SUPPRESSED, expected_version=seen_by_second.row_version
            )
    with factory(ws) as check:
        assert check.companies.get(company.id).status is S.RESEARCHED


def test_leaving_without_commit_discards_everything(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        new_company(uow)
    with factory(ws) as uow:
        assert uow.companies.known_domains() == set()


# ------------------------------------------------------------------ operator input wins


def test_an_operator_change_applies_and_protects_the_field(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        company = new_company(uow)
        changed = uow.companies.update_fields(
            company.id,
            {"name": "Acme Ltd", "country_code": "gb"},
            actor=OPERATOR,
            expected_version=company.row_version,
        )
        assert (changed.name, changed.country_code) == ("Acme Ltd", "GB")
        assert set(changed.manual_fields) == {"name", "country_code"}
        events = [
            e
            for e in uow.events.for_entity(EntityType.COMPANY, company.id)
            if e.type == "field_changed"
        ]
        assert [e.data["applied"] for e in events] == [True, True]


def test_the_engine_cannot_overwrite_an_operator_value_but_the_attempt_is_recorded(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        company = new_company(uow)
        company = uow.companies.update_fields(
            company.id, {"name": "Acme Ltd"}, actor=OPERATOR, expected_version=company.row_version
        )
        after = uow.companies.update_fields(
            company.id,
            {"name": "ACME LIMITED"},
            actor=provider("tavily"),
            expected_version=company.row_version,
        )
        assert after.name == "Acme Ltd"
        assert after.row_version == company.row_version  # nothing changed, so no new version
        skipped = [
            e
            for e in uow.events.for_entity(EntityType.COMPANY, company.id)
            if e.data.get("applied") is False
        ]
        (event,) = skipped
        assert event.data == {
            "field": "name",
            "old": "Acme Ltd",
            "new": "ACME LIMITED",
            "source": "provider:tavily",
            "applied": False,
        }


def test_the_engine_can_write_fields_the_operator_has_not_touched(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        company = new_company(uow)
        updated = uow.companies.update_fields(
            company.id,
            {"fit_score": 80, "research": {"summary": "x"}},
            actor=provider("llm"),
            expected_version=company.row_version,
        )
        assert updated.fit_score == 80 and updated.research == {"summary": "x"}
        assert updated.manual_fields == ()


def test_an_unchanged_value_is_not_a_change(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        company = new_company(uow, name="Acme")
        same = uow.companies.update_fields(
            company.id, {"name": "Acme"}, actor=OPERATOR, expected_version=company.row_version
        )
        assert same.manual_fields == () and same.row_version == company.row_version
        assert event_types(uow, company.id) == ["created"]


def test_fields_outside_the_editable_set_are_refused(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        company = new_company(uow)
        for forbidden in ("status", "domain", "row_version", "workspace_id", "manual_fields"):
            with pytest.raises(ValueError, match=forbidden):
                uow.companies.update_fields(
                    company.id,
                    {forbidden: "x"},
                    actor=OPERATOR,
                    expected_version=company.row_version,
                )


# ------------------------------------------------------------------ the queue


def test_due_orders_by_priority_and_skips_scheduled_future_work(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    now = utcnow()
    with factory(ws) as uow:
        low = new_company(uow, "low.com", priority=9)
        high = new_company(uow, "high.com", priority=1)
        future = new_company(uow, "future.com", priority=1)
        past = new_company(uow, "past.com", priority=5)
        done = new_company(uow, "done.com", priority=1)
        uow.companies.update_fields(
            future.id, {"next_action_at": now + timedelta(days=1)}, actor=SYSTEM, expected_version=1
        )
        uow.companies.update_fields(
            past.id, {"next_action_at": now - timedelta(days=1)}, actor=SYSTEM, expected_version=1
        )
        uow.companies.transition(done.id, S.RESEARCHED, expected_version=1)
        uow.commit()
        due = uow.companies.due(S.NEW, 10, now=now)
        assert [c.domain for c in due] == ["high.com", "past.com", "low.com"]
        assert [c.id for c in uow.companies.due(S.NEW, 1, now=now)] == [high.id]
        assert low.id in {c.id for c in due}
        assert [c.domain for c in uow.companies.due(S.RESEARCHED, 10)] == ["done.com"]
        assert uow.companies.count_by_status() == {S.NEW: 4, S.RESEARCHED: 1}
