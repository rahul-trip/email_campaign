"""The directory through the API: a lead's badge, reporting, skipping, and the admin screen."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from outbound.api.deps import Services
from outbound.domain.enums import (
    CompanySource,
    ContactSource,
    EmailStatus,
    PlatformRole,
    Provenance,
)
from outbound.providers.adapters.transactional_email import LogEmail
from outbound.services.directory import DirectoryService
from tests.api.conftest import Api, add_user, sign_in

STAFF = "dir@platform.example"


@pytest.fixture
def lead(services: Services) -> str:
    """A lead whose person has a primary address that another run already verified."""
    with services.container.uow(services.workspace_id) as uow:
        company = uow.companies.create(domain="acme.com", source=CompanySource.MANUAL)
        contact = uow.contacts.add(
            company.id, rank=1, source=ContactSource.SITE, full_name="Jane Doe"
        )
        uow.emails.add(
            contact.id, "jane.doe@acme.com", Provenance.API_DATABASE,
            status=EmailStatus.VALID, is_primary=True,
        )  # fmt: skip
        uow.directory.observe_email(
            email="jane.doe@acme.com", domain="acme.com", first_name="Jane", last_name="Doe",
            full_name="Jane Doe", title=None, provenance="api_database", source="hunter",
            verified_by="v", observed_at=datetime.now(UTC),
        )  # fmt: skip
        uow.commit()
    DirectoryService(services.container.platform, finder_price_micro_usd=1).run()
    return company.id


@pytest.fixture
def staff(app_and_services: tuple[FastAPI, Services]) -> Api:
    app, _ = app_and_services
    add_user(app, STAFF, platform_role=PlatformRole.ADMIN)
    return sign_in(app, STAFF)


def test_a_lead_shows_that_the_directory_backs_its_address_by_month_only(
    api: Api, lead: str
) -> None:
    badge = api.get(f"/api/companies/{lead}/directory").json()
    assert badge["in_directory"] is True
    assert len(badge["verified_month"]) == 7 and badge["skipping"] is False
    assert set(badge) == {"in_directory", "verified_month", "can_skip", "skipping"}


def test_a_report_stops_the_address_being_served_and_reaches_the_admin_screen(
    api: Api, staff: Api, lead: str, services: Services
) -> None:
    assert (
        api.post(f"/api/companies/{lead}/directory/report", json={"field": "bogus"}).status_code
        == 422
    )
    done = api.post(
        f"/api/companies/{lead}/directory/report", json={"field": "still_works", "reason": "left"}
    )
    assert done.status_code == 204
    with services.container.uow(services.workspace_id) as uow:
        assert uow.directory.find_email("acme.com", "Jane", "Doe", datetime.now(UTC)) is None
        # and this workspace no longer uses the address it called wrong
        held = uow.emails.by_address("jane.doe@acme.com")
        assert held is not None and held.status is EmailStatus.INVALID
    overview = staff.get("/api/admin/directory").json()
    assert overview["figures"]["open_reports"] == 1
    [flag] = overview["flags"]
    assert flag["target_key"] == "jane.doe@acme.com" and "reporter" not in str(flag)
    after = staff.post(
        f"/api/admin/directory/flags/{flag['id']}/resolve", json={"accept": False, "note": "no"}
    ).json()
    assert after["flags"] == []
    with services.container.uow(services.workspace_id) as uow:
        assert uow.directory.find_email("acme.com", "Jane", "Doe", datetime.now(UTC))


def test_skipping_the_directory_needs_the_ability(
    api: Api, staff: Api, lead: str, services: Services
) -> None:
    with services.container.platform() as p:
        p.plans.set_plan(
            services.workspace_id, "free", started_at=datetime.now(UTC) - timedelta(days=1),
            access_until=datetime.now(UTC) + timedelta(days=29),
        )  # fmt: skip
        p.commit()
    refused = api.put(f"/api/companies/{lead}/directory/skip", json={"skip": True})
    assert refused.status_code == 422 and "plan" in refused.text
    with services.container.platform() as p:
        p.plans.add_override(  # an admin gave this customer the ability
            services.workspace_id, "feature.directory_bypass", True, note="pilot"
        )
        p.commit()
    ok = api.put(f"/api/companies/{lead}/directory/skip", json={"skip": True})
    assert ok.status_code == 200 and ok.json()["skipping"] is True and ok.json()["can_skip"] is True


def test_only_staff_see_the_admin_directory(api: Api, staff: Api, lead: str) -> None:
    assert api.get("/api/admin/directory").status_code == 403
    assert staff.get("/api/admin/directory").status_code == 200
    history = staff.get("/api/admin/directory/history", params={"key": "jane.doe@acme.com"}).json()
    assert history and set(history[0]) == {"at", "target", "source"}  # no contributor


def test_a_person_removes_themselves_from_the_directory_by_confirming_by_email(
    anonymous: TestClient, lead: str, services: Services, outbox: LogEmail, staff: Api
) -> None:
    headers = {"X-Requested-With": "outbound"}
    asked = anonymous.post(
        "/api/auth/remove-my-data", json={"email": "Jane.Doe@acme.com"}, headers=headers
    )
    assert asked.status_code == 202
    [mail] = [m for m in outbox.sent if m.to == "jane.doe@acme.com"]
    token = re.search(r"remove-my-data\?token=([\w-]+)", mail.text).group(1)  # type: ignore[union-attr]
    still = anonymous.post(
        "/api/auth/remove-my-data/confirm", json={"token": "wrong"}, headers=headers
    )
    assert still.status_code == 400
    with services.container.uow(services.workspace_id) as uow:
        assert uow.directory.holds("jane.doe@acme.com")  # nothing changes until it is confirmed
    done = anonymous.post(
        "/api/auth/remove-my-data/confirm", json={"token": token}, headers=headers
    )
    assert done.status_code == 200
    with services.container.uow(services.workspace_id) as uow:
        assert not uow.directory.holds("jane.doe@acme.com")
    DirectoryService(services.container.platform, finder_price_micro_usd=0).run()
    again = anonymous.post(
        "/api/auth/remove-my-data/confirm", json={"token": token}, headers=headers
    )
    assert again.status_code == 400  # a link works once
    audit = staff.get("/api/admin/audit", params={"action": "directory_removal_confirmed"}).json()
    assert len(audit) == 1 and "jane" not in str(audit)  # the address is not written down


# ------------------------------------------------------------------ staff browse, add, edit, remove


def test_staff_browse_add_edit_and_remove_directory_entries(
    staff: Api, api: Api, lead: str, services: Services
) -> None:
    listed = staff.get("/api/admin/directory/entries").json()
    assert listed["total"] == 1 and listed["entries"][0]["email"] == "jane.doe@acme.com"
    assert staff.get("/api/admin/directory/entries", params={"q": "nobody"}).json()["total"] == 0
    assert staff.get("/api/admin/directory/entries", params={"q": "ACME"}).json()["total"] == 1
    assert api.get("/api/admin/directory/entries").status_code == 403

    new = {"email": "sam.lee@acme.com", "first_name": "Sam", "last_name": "Lee",
           "company_domain": "acme.com", "title": "CTO"}  # fmt: skip
    made = staff.post("/api/admin/directory/entries", json=new)
    assert made.status_code == 201 and made.json()["source"] == "staff"
    assert staff.post("/api/admin/directory/entries", json=new).status_code == 422  # twice
    with services.container.uow(services.workspace_id) as uow:  # served like any fact
        assert uow.directory.find_email("acme.com", "Sam", "Lee", datetime.now(UTC))

    entry = made.json()["id"]
    changed = staff.patch(
        f"/api/admin/directory/entries/{entry}",
        json={
            "title": "CEO",
            "employment_status": "left",
            "linkedin_url": "https://www.linkedin.com/in/sam",
        },
    ).json()
    assert changed["title"] == "CEO" and changed["employment_status"] == "left"
    with services.container.uow(services.workspace_id) as uow:  # someone who left is not served
        assert uow.directory.find_email("acme.com", "Sam", "Lee", datetime.now(UTC)) is None
    staff.patch(f"/api/admin/directory/entries/{entry}", json={"status": "invalid"})
    assert (
        staff.patch(f"/api/admin/directory/entries/{entry}", json={"status": "bogus"}).status_code
        == 422
    )

    assert (
        staff.delete(f"/api/admin/directory/entries/{entry}", params={"block": "true"}).status_code
        == 204
    )
    assert (
        staff.post("/api/admin/directory/entries", json=new).status_code == 422
    )  # blocked for good
    assert staff.get("/api/admin/directory/entries").json()["total"] == 1
    actions = {e["action"] for e in staff.get("/api/admin/audit").json()}
    assert {
        "directory_entry_added",
        "directory_entry_changed",
        "directory_entry_removed",
    } <= actions


def test_staff_manage_the_directorys_company_patterns(staff: Api, lead: str) -> None:
    saved = staff.put(
        "/api/admin/directory/companies/Acme.com",
        json={"name": "Acme", "country_code": "gb", "email_pattern": "{first}.{last}"},
    ).json()
    assert saved["domain"] == "acme.com" and saved["country_code"] == "GB"
    assert saved["pattern_confidence"] == 3
    assert staff.get("/api/admin/directory/companies").json()["total"] == 1
    assert staff.put("/api/admin/directory/companies/nodots", json={}).status_code == 422
    assert staff.delete("/api/admin/directory/companies/acme.com").status_code == 204
    assert staff.get("/api/admin/directory/companies").json()["total"] == 0
