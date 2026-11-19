"""Find more people by role: one lead, or up to twenty, and what to do with who is found."""

from __future__ import annotations

import pytest
from fastapi import FastAPI

from outbound.api.app import create_app
from outbound.api.deps import build_services
from outbound.bootstrap import Container
from outbound.domain.enums import CompanySource, CompanyStatus, ContactSource
from outbound.providers.adapters.transactional_email import LogEmail
from tests.api.conftest import ADMIN, Api, add_user, sign_in
from tests.db.test_person_actions import hit
from tests.stages.fakes import FakeLlm, FakeSearch
from tests.stages.world import PROFILE

RITA = hit(
    "https://www.linkedin.com/in/rita-hunt", "Rita Hunt - Technical Recruiter - Acme | LinkedIn"
)


@pytest.fixture
def finding(container: Container, ws: str) -> tuple[Api, str]:
    """A signed-in client over services that can search, and a failed lead with one person."""
    with container.uow(ws) as uow:
        uow.own_workspace.set_sender_profile(PROFILE)
        company = uow.companies.create(domain="acme.com", source=CompanySource.MANUAL, name="Acme")
        version = company.row_version
        for step in (
            CompanyStatus.RESEARCHED,
            CompanyStatus.QUALIFIED,
            CompanyStatus.CONTACTS_FOUND,
        ):
            version = uow.companies.transition(
                company.id, step, expected_version=version
            ).row_version
        uow.companies.transition(
            company.id, CompanyStatus.FAILED, expected_version=version, failed_stage="email"
        )
        uow.contacts.add(company.id, rank=1, source=ContactSource.SITE, full_name="Jane Doe")
        uow.commit()
        company_id = company.id
    services = build_services(container, ws, search=FakeSearch(hits=[RITA]), writer=FakeLlm())
    app: FastAPI = create_app(services, web_dist=None, email=LogEmail())
    add_user(app, ADMIN, ws)
    return sign_in(app, ADMIN, ws), company_id


def test_roles_and_what_to_do_with_them_are_chosen_per_request(finding: tuple[Api, str]) -> None:
    api, company_id = finding
    body = api.post(
        f"/api/companies/{company_id}/find-people", json={"roles": ["Recruiter"], "reach": "both"}
    ).json()
    assert (body["added"], body["retried"]) == (1, False)
    [rita] = body["people"]
    assert (rita["name"], rita["confirmed"], rita["email"], rita["linkedin"]) == (
        "Rita Hunt",
        True,
        "asked",
        "written",
    )
    assert body["queued_run_id"]  # a run looks for the address
    assert (
        api.get(f"/api/companies/{company_id}/linkedin").json()[0]["contact_id"]
        == rita["contact_id"]
    )


def test_no_body_still_does_the_old_search_for_who_decides(finding: tuple[Api, str]) -> None:
    api, company_id = finding
    body = api.post(f"/api/companies/{company_id}/find-people").json()
    assert body["queued_run_id"] is None  # nothing was asked for
    assert all(p["email"] == "" and p["linkedin"] == "" for p in body["people"])


def test_the_roles_are_limited_and_the_reach_must_be_one_of_four(finding: tuple[Api, str]) -> None:
    api, company_id = finding
    url = f"/api/companies/{company_id}/find-people"
    assert api.post(url, json={"roles": ["a", "b", "c", "d", "e"]}).status_code == 422
    assert api.post(url, json={"reach": "carrier pigeon"}).status_code == 422


def test_many_leads_at_once_report_each_and_queue_one_run(finding: tuple[Api, str]) -> None:
    api, company_id = finding
    out = api.post(
        "/api/companies/find-people",
        json={"company_ids": [company_id, "nope"], "roles": ["Recruiter"], "reach": "email"},
    ).json()
    first, missing = out["leads"]
    assert (first["company_id"], first["added"], first["email_asked"]) == (company_id, 1, 1)
    assert missing["company_id"] == "nope" and missing["error"]
    assert out["queued_run_id"]
    assert api.post("/api/companies/find-people", json={"company_ids": []}).status_code == 422
    too_many = {"company_ids": [str(n) for n in range(21)]}
    assert api.post("/api/companies/find-people", json=too_many).status_code == 422
