"""Notices about credits and access (Phase 6d.8): sent once, to the right people."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI

from outbound.api.deps import Services
from outbound.domain.enums import PlatformRole
from outbound.providers.adapters.transactional_email import LogEmail
from outbound.services.admin import AdminService
from outbound.services.notices import NoticeService
from tests.api.conftest import ADMIN, Api, add_user, sign_in

STAFF = "ops@notices.example"


@pytest.fixture
def notices(app_and_services: tuple[FastAPI, Services], outbox: LogEmail) -> NoticeService:
    app, services = app_and_services
    c = services.container
    with c.platform() as p:
        p.plans.set_plan(
            services.workspace_id, "free", started_at=datetime.now(UTC) - timedelta(days=1),
            access_until=datetime.now(UTC) + timedelta(days=3),
        )  # fmt: skip
        p.commit()
    add_user(app, STAFF, platform_role=PlatformRole.ADMIN)
    outbox.sent.clear()
    return NoticeService(
        AdminService(c.platform, c.identity, c.uow), c.identity, outbox, "https://app.example"
    )


def to(outbox: LogEmail, address: str) -> list[str]:
    return [m.subject for m in outbox.sent if m.to == address]


def test_a_workspace_admin_hears_once_when_a_step_runs_low_and_when_access_nears_its_end(
    api: Api, notices: NoticeService, outbox: LogEmail
) -> None:
    for n in range(4):  # 4 of the free plan's 5 manual leads: 80%
        api.post("/api/targets", json={"website": f"low{n}.com", "country": "UK"})
    notices.run()
    subjects = to(outbox, ADMIN)
    assert any("manual credits at 80%" in s for s in subjects)
    assert any("access ends" in s for s in subjects)
    before = len(outbox.sent)
    notices.run()
    assert len(outbox.sent) == before  # nothing is sent twice
    api.post("/api/targets", json={"website": "last.com", "country": "UK"})
    notices.run()
    assert any("manual credits at 100%" in s for s in to(outbox, ADMIN))


def test_a_grant_reaches_the_customer_and_a_request_reaches_staff(
    api: Api, app_and_services: tuple[FastAPI, Services], notices: NoticeService, outbox: LogEmail
) -> None:
    app, services = app_and_services
    staff = sign_in(app, STAFF)
    assert (
        api.post("/api/usage/request-credits", json={"step": "manual", "note": "pilot"}).status_code
        < 300
    )
    staff.post(
        f"/api/admin/customers/{services.workspace_id}/grants",
        json={"step": "manual", "amount": 10, "note": "", "resume_now": False},
    )
    notices.run()
    assert any("10 manual credits added" in s for s in to(outbox, ADMIN))
    assert any("asked for more credits" in s for s in to(outbox, STAFF))
    assert not any("asked for more credits" in s for s in to(outbox, ADMIN))
