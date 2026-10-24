"""Every endpoint through the real app, services and database."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from outbound.api.deps import Services
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.entities import CountryPolicy
from outbound.domain.enums import (
    CallOutcome,
    CompanySource,
    CompanyStatus,
    ContactSource,
    EmailStatus,
    EntityType,
    HoldReason,
    MessageState,
    PolicyRule,
    Provenance,
)
from outbound.services.dns_check import TxtLookup
from tests.api.conftest import ADMIN, HEADERS, WEBHOOK_SECRET, Api, sign_in

C = CompanyStatus
FOOTER = 'Quantra Inc, 1 Main St. Reply "unsubscribe" and we will stop.'
BODY = f"Hi Jane,\n\nI saw the Leeds office. Would a call help?\n\nSam Lee\n\n--\n{FOOTER}"


def company_id(api: Api, domain: str) -> str:
    page = api.get("/api/companies", params={"q": domain}).json()
    return str(page["items"][0]["id"])


# ------------------------------------------------------------------ targets


def test_quick_add_creates_a_company(api: Api) -> None:
    response = api.post("/api/targets", json={"website": "https://www.acme.com", "country": "UK"})
    assert response.status_code == 200
    [row] = response.json()["rows"]
    assert (row["status"], row["domain"]) == ("accepted", "acme.com")
    page = api.get("/api/companies").json()
    assert page["total"] == 1 and page["items"][0]["country_code"] == "GB"


def test_quick_add_can_only_validate(api: Api) -> None:
    body = api.post("/api/targets", json={"website": "acme.com", "validate_only": True}).json()
    assert body["validate_only"] is True and body["batch_id"] is None
    assert api.get("/api/companies").json()["total"] == 0


def test_a_company_name_without_a_search_waits_and_can_be_confirmed(api: Api) -> None:
    [row] = api.post("/api/targets", json={"company": "Acme Energy"}).json()["rows"]
    assert row["status"] == "needs_confirmation"
    [waiting] = api.get("/api/targets/waiting").json()
    assert waiting["id"] == row["row_id"]
    confirmed = api.post(
        f"/api/targets/{row['row_id']}/confirm", json={"domain": "acme-energy.com"}
    )
    assert confirmed.json()["status"] == "accepted"
    assert api.get("/api/targets/waiting").json() == []
    assert api.post("/api/targets/nope/confirm", json={"domain": "x.com"}).status_code == 404
    assert (
        api.post(f"/api/targets/{row['row_id']}/confirm", json={"domain": "x.com"}).status_code
        == 422
    )


def test_an_upload_is_previewed_then_committed(api: Api) -> None:
    data = b"Company,Website\nAcme,acme.com\nBeta,beta.io\nBeta again,beta.io\n"
    files = {"file": ("targets.csv", data, "text/csv")}
    preview = api.post("/api/targets/upload", files=files).json()
    assert [r["status"] for r in preview["rows"]] == ["accepted", "accepted", "merged"]
    assert api.get("/api/companies").json()["total"] == 0

    committed = api.post("/api/targets/upload", files=files, data={"preview": "false"}).json()
    assert committed["batch_id"] is not None
    assert api.get("/api/companies").json()["total"] == 2


def test_an_upload_of_the_wrong_kind_is_a_clear_error(api: Api) -> None:
    response = api.post(
        "/api/targets/upload", files={"file": ("x.pdf", b"%PDF", "application/pdf")}
    )
    assert response.status_code == 422 and "csv or .xlsx" in response.json()["detail"]


def test_editing_a_saved_target_needs_the_current_version(api: Api) -> None:
    api.post("/api/targets", json={"website": "acme.com"})
    company = api.get("/api/companies").json()["items"][0]
    edited = api.patch(
        f"/api/companies/{company['id']}",
        json={"row_version": company["row_version"], "name": "Acme Ltd", "priority": 2},
    )
    assert edited.status_code == 200
    assert (edited.json()["name"], edited.json()["priority"]) == ("Acme Ltd", 2)
    assert "name" in edited.json()["manual_fields"]
    stale = api.patch(
        f"/api/companies/{company['id']}",
        json={"row_version": company["row_version"], "name": "Stale"},
    )
    assert stale.status_code == 409 and stale.json()["code"] == "version_conflict"


# ------------------------------------------------------------------ leads


def seed_company(
    factory: UnitOfWorkFactory,
    ws: str,
    domain: str,
    *path: CompanyStatus,
    hold: HoldReason | None = None,
    failed_stage: str | None = None,
) -> str:
    with factory(ws) as uow:
        company = uow.companies.create(domain=domain, source=CompanySource.MANUAL)
        version = company.row_version
        for step in path:
            extra: dict[str, object] = {}
            if step is C.HELD:
                extra["hold_reason"] = hold
            if step is C.FAILED:
                extra.update(failed_stage=failed_stage, last_error="boom")
            version = uow.companies.transition(
                company.id,
                step,
                expected_version=version,
                **extra,  # type: ignore[arg-type]
            ).row_version
        uow.commit()
        return company.id


def test_leads_are_listed_filtered_and_paged(api: Api, factory: UnitOfWorkFactory, ws: str) -> None:
    seed_company(factory, ws, "acme.com")
    seed_company(factory, ws, "beta.io", C.RESEARCHED)
    seed_company(factory, ws, "gamma.io", C.RESEARCHED, C.HELD, hold=HoldReason.COUNTRY_UNKNOWN)
    assert api.get("/api/companies").json()["total"] == 3
    assert [c["domain"] for c in api.get("/api/companies?status=researched").json()["items"]] == [
        "beta.io"
    ]
    held = api.get("/api/companies?hold_reason=country_unknown").json()
    assert held["items"][0]["domain"] == "gamma.io"
    page = api.get("/api/companies?limit=2&offset=2").json()
    assert (len(page["items"]), page["total"]) == (1, 3)
    assert api.get("/api/companies?status=bogus").status_code == 422


def test_a_lead_has_detail_a_timeline_and_a_waterfall(
    api: Api, factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = seed_company(factory, ws, "acme.com", C.RESEARCHED)
    with factory(ws) as uow:
        contact = uow.contacts.add(cid, rank=1, source=ContactSource.SITE, full_name="Jane Doe")
        uow.emails.add(contact.id, "jane@acme.com", Provenance.API_DATABASE, is_primary=True)
        uow.calls.record(
            provider="hunter",
            operation="find",
            request_hash="h",
            outcome=CallOutcome.HIT,
            cost_micro_usd=24_500,
            company_id=cid,
        )
        uow.commit()
    detail = api.get(f"/api/companies/{cid}").json()
    assert detail["company"]["domain"] == "acme.com"
    assert detail["contacts"][0]["emails"][0]["email"] == "jane@acme.com"
    kinds = {
        (e["entity_type"], e["type"]) for e in api.get(f"/api/companies/{cid}/timeline").json()
    }
    assert {("company", "created"), ("contact", "created")} <= kinds
    [step] = api.get(f"/api/companies/{cid}/waterfall").json()
    assert (step["provider"], step["outcome"], step["cost_micro_usd"]) == ("hunter", "hit", 24_500)


def test_retry_release_and_requalify(api: Api, factory: UnitOfWorkFactory, ws: str) -> None:
    failed = seed_company(factory, ws, "a.com", C.FAILED, failed_stage="research")
    held = seed_company(factory, ws, "b.com", C.RESEARCHED, C.HELD, hold=HoldReason.COUNTRY_UNKNOWN)
    out = seed_company(factory, ws, "c.com", C.RESEARCHED, C.DISQUALIFIED)
    assert api.post(f"/api/companies/{failed}/retry").json()["status"] == "new"
    unchanged = api.post(f"/api/companies/{held}/release-hold", json={})
    assert unchanged.status_code == 409 and "Nothing has changed" in unchanged.json()["detail"]
    company = api.get(f"/api/companies/{held}").json()["company"]
    api.patch(
        f"/api/companies/{held}",
        json={"row_version": company["row_version"], "country_code": "US"},
    )
    assert api.post(f"/api/companies/{held}/release-hold", json={}).json()["status"] == "researched"
    assert api.post(f"/api/companies/{out}/requalify").json()["status"] == "qualified"
    again = api.post(f"/api/companies/{failed}/retry")
    assert again.status_code == 409 and again.json()["code"] == "action_not_allowed"


def test_a_hold_with_no_default_takes_the_operators_choice(
    api: Api, factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = seed_company(factory, ws, "a.com", C.RESEARCHED, C.HELD, hold=HoldReason.NEEDS_OPERATOR)
    assert api.post(f"/api/companies/{cid}/release-hold", json={}).status_code == 409
    ok = api.post(f"/api/companies/{cid}/release-hold", json={"resume_to": "researched"})
    assert ok.json()["status"] == "researched"


def test_consent_is_recorded_for_a_contact(api: Api, factory: UnitOfWorkFactory, ws: str) -> None:
    cid = seed_company(factory, ws, "a.com")
    with factory(ws) as uow:
        contact = uow.contacts.add(cid, rank=1, source=ContactSource.SITE)
        uow.commit()
    ok = api.post(
        f"/api/contacts/{contact.id}/consents",
        json={"basis": "express", "evidence": "replied yes by email"},
    )
    assert ok.status_code == 201 and ok.json()["basis"] == "express"
    blank = api.post(
        f"/api/contacts/{contact.id}/consents", json={"basis": "express", "evidence": " "}
    )
    assert blank.status_code == 409


# ------------------------------------------------------------------ review


def seed_review(factory: UnitOfWorkFactory, ws: str, domain: str = "acme.com") -> tuple[str, str]:
    with factory(ws) as uow:
        company = uow.companies.create(domain=domain, source=CompanySource.MANUAL, name="Acme")
        version = company.row_version
        for step in (C.RESEARCHED, C.QUALIFIED, C.CONTACTS_FOUND, C.EMAIL_READY, C.COPY_READY):
            version = uow.companies.transition(
                company.id, step, expected_version=version
            ).row_version
        contact = uow.contacts.add(
            company.id, rank=1, source=ContactSource.SITE, full_name="Jane Doe", title="CTO"
        )
        address = uow.emails.add(
            contact.id,
            f"jane@{domain}",
            Provenance.API_DATABASE,
            status=EmailStatus.VALID,
            is_primary=True,
        )
        message = uow.messages.create(
            company_id=company.id,
            contact_id=contact.id,
            contact_email_id=address.id,
            step=0,
            subject="leeds forecasts",
            generated_body=BODY,
            lint_report={"flagged": True, "issues": [{"rule": "length", "message": "short"}]},
        )
        uow.commit()
        return company.id, message.id


def test_the_review_queue_shows_the_email_with_context(
    api: Api, factory: UnitOfWorkFactory, ws: str
) -> None:
    _, mid = seed_review(factory, ws)
    [item] = api.get("/api/review").json()
    assert item["message"]["id"] == mid and item["flagged"] is True
    assert item["contact"]["emails"][0]["email"] == "jane@acme.com"
    detail = api.get(f"/api/review/{mid}").json()
    assert detail["item"]["company"]["domain"] == "acme.com"


def test_approving_with_an_edit_stores_both_texts(
    api: Api, factory: UnitOfWorkFactory, ws: str
) -> None:
    cid, mid = seed_review(factory, ws)
    edited = BODY.replace("Would a call help?", "Free for a call?")
    response = api.post(f"/api/review/{mid}/approve", json={"edited_body": edited})
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "approved" and body["final_body"] == edited
    assert body["generated_body"] == BODY and 0 < body["edit_distance"] < 1
    assert api.get(f"/api/companies/{cid}").json()["company"]["status"] == "approved"


def test_an_edit_that_drops_the_footer_is_refused(
    api: Api, factory: UnitOfWorkFactory, ws: str
) -> None:
    _, mid = seed_review(factory, ws)
    response = api.post(f"/api/review/{mid}/approve", json={"edited_body": "Hi Jane, short note?"})
    assert response.status_code == 409 and "footer" in response.json()["detail"]


def test_a_stale_message_version_is_a_conflict(
    api: Api, factory: UnitOfWorkFactory, ws: str
) -> None:
    _, mid = seed_review(factory, ws)
    version = api.get(f"/api/review/{mid}").json()["item"]["message"]["row_version"]
    stale = api.post(f"/api/review/{mid}/approve", json={"row_version": version + 5})
    assert stale.status_code == 409 and stale.json()["code"] == "version_conflict"
    assert api.post(f"/api/review/{mid}/approve", json={"row_version": version}).status_code == 200


def test_rejecting_needs_a_reason_and_a_message_is_reviewed_once(
    api: Api, factory: UnitOfWorkFactory, ws: str
) -> None:
    cid, mid = seed_review(factory, ws)
    assert api.post(f"/api/review/{mid}/reject", json={"reason": " "}).status_code == 409
    assert api.post(f"/api/review/{mid}/reject", json={"reason": "wrong person"}).status_code == 200
    assert api.get(f"/api/companies/{cid}").json()["company"]["status"] == "rejected"
    again = api.post(f"/api/review/{mid}/approve", json={})
    assert again.status_code == 409 and again.json()["code"] == "action_not_allowed"


# ------------------------------------------------------------------ runs and reports


def test_a_run_is_queued_and_can_be_cancelled(api: Api) -> None:
    queued = api.post("/api/runs", json={"limit": 5, "mode": "manual", "only": ["research"]})
    assert queued.status_code == 202
    run = queued.json()
    assert run["status"] == "queued" and run["params"]["limit"] == 5
    assert api.get(f"/api/runs/{run['id']}").json()["status"] == "queued"
    assert [r["id"] for r in api.get("/api/runs").json()] == [run["id"]]
    assert api.post(f"/api/runs/{run['id']}/cancel").json()["status"] == "cancelled"
    assert api.post("/api/runs", json={"limit": 0}).status_code == 422


def test_status_counts_leads_holds_and_the_review_queue(
    api: Api, factory: UnitOfWorkFactory, ws: str
) -> None:
    seed_review(factory, ws)
    seed_company(factory, ws, "b.com", C.RESEARCHED, C.HELD, hold=HoldReason.ENTITY_UNKNOWN)
    body = api.get("/api/status").json()
    assert body["by_status"] == {"copy_ready": 1, "held": 1}
    assert body["held"] == {"entity_unknown": 1} and body["waiting_for_review"] == 1


def test_reports_are_available(api: Api) -> None:
    quality = api.get("/api/reports/quality").json()
    assert (quality["sent"], quality["unedited_share"]) == (0, None)
    cost = api.get("/api/reports/cost?days=7").json()
    assert (cost["total"], cost["paid_calls"]) == (0, 0)
    assert api.get("/api/reports/cost?days=0").status_code == 422


# ------------------------------------------------------------------ settings


def test_the_sender_profile_and_workspace_settings_can_be_edited(api: Api) -> None:
    put = api.put("/api/settings/sender-profile", json={"legal_name": "Quantra Inc"})
    assert put.json()["legal_name"] == "Quantra Inc"
    assert api.get("/api/settings/sender-profile").json()["legal_name"] == "Quantra Inc"
    assert api.put("/api/settings/sender-profile", json={"nope": 1}).status_code == 422
    assert api.put("/api/settings/workspace", json={"few_shot_examples": 2}).status_code == 200
    blocked = api.put("/api/settings/workspace", json={"send_enabled": True})
    assert blocked.status_code == 422  # not a setting an operator can change at all
    assert "send_enabled" in {e["field"] for e in blocked.json()["errors"]}


def test_settings_are_checked_for_type_and_size(api: Api) -> None:
    url = "/api/settings/workspace"
    assert api.put(url, json={"budget_per_prospect_micro_usd": "lots"}).status_code == 422
    assert api.put(url, json={"budget_per_prospect_micro_usd": -5}).status_code == 422
    assert api.put(url, json={"few_shot_examples": 99}).status_code == 422
    assert (
        api.put("/api/settings/sender-profile", json={"narrative": "x" * 20_000}).status_code == 422
    )
    assert (
        api.put(
            "/api/settings/sender-profile", json={"value_propositions": "not a list"}
        ).status_code
        == 422
    )


def test_a_null_means_no_budget_ceiling_but_is_ignored_for_everything_else(api: Api) -> None:
    url = "/api/settings/workspace"
    api.put(url, json={"budget_per_prospect_micro_usd": 250_000, "few_shot_examples": 3})
    after = api.put(
        url, json={"budget_per_prospect_micro_usd": None, "few_shot_examples": None}
    ).json()
    assert after["budget_per_prospect_micro_usd"] is None  # cleared: no ceiling
    assert after["few_shot_examples"] == 3  # a null here would have crashed the writer


def test_changes_to_safety_settings_are_recorded_in_the_audit_trail(
    api: Api, factory: UnitOfWorkFactory, ws: str
) -> None:
    api.put("/api/settings/workspace", json={"safe_to_send_only": False})
    api.put("/api/settings/sender-profile", json={"legal_name": "Quantra"})
    with factory(ws) as uow:
        events = {e.type: e.data for e in uow.events.for_entity(EntityType.WORKSPACE, ws)}
    assert events["settings_changed"] == {"safe_to_send_only": False}
    assert events["sender_profile_reviewed"] == {"fields": ["legal_name"]}


def test_campaigns_can_be_created_listed_and_changed(api: Api) -> None:
    created = api.post(
        "/api/settings/campaigns",
        json={"name": "expo", "target_titles": ["CTO"], "research_questions": ["Do they trade?"]},
    )
    assert created.status_code == 201
    cid = created.json()["id"]
    patched = api.patch(f"/api/settings/campaigns/{cid}", json={"min_fit_score": 75})
    assert patched.json()["min_fit_score"] == 75
    assert [c["name"] for c in api.get("/api/settings/campaigns").json()] == ["expo"]
    dup = api.post("/api/settings/campaigns", json={"name": "expo", "target_titles": ["CEO"]})
    assert dup.status_code == 422
    assert (
        api.post(
            "/api/settings/campaigns", json={"name": "x", "target_titles": [], "min_fit_score": 500}
        ).status_code
        == 422
    )


def test_a_country_policy_is_versioned_when_it_changes(api: Api) -> None:
    first = api.put("/api/settings/policies/gb", json={"rule": "allow_with_footer"}).json()
    assert (first["country_code"], first["version"]) == ("GB", 1)
    changed = api.put(
        "/api/settings/policies/GB",
        json={"rule": "block", "reviewed_by": "lawyer@firm"},
    ).json()
    assert (changed["version"], changed["reviewed_by"]) == (2, "lawyer@firm")
    assert [p["country_code"] for p in api.get("/api/settings/policies").json()] == ["GB"]
    assert api.put("/api/settings/policies/GBR", json={"rule": "block"}).status_code == 422


def test_suppressions_are_add_only_and_show_no_personal_data(api: Api) -> None:
    added = api.post(
        "/api/settings/suppressions",
        json={"kind": "email", "value": "jane@acme.com", "reason": "opt_out"},
    )
    assert added.status_code == 201 and added.json() == {"added": True}
    again = api.post(
        "/api/settings/suppressions",
        json={"kind": "email", "value": "JANE@acme.com", "reason": "opt_out"},
    )
    assert again.json() == {"added": False}
    [entry] = api.get("/api/settings/suppressions").json()
    assert "acme" not in json.dumps(entry) and len(entry["fingerprint"]) == 10


def test_a_mailbox_dns_check_is_run_from_the_settings_screen(
    make_app: Callable[..., tuple[FastAPI, Services]],
) -> None:
    records = {"quantra.example": ["v=spf1 -all"], "_dmarc.quantra.example": ["v=DMARC1; p=reject"]}
    lookup: TxtLookup = lambda name: records.get(name, [])  # noqa: E731
    app, services = make_app(dns_lookup=lookup)
    api = sign_in(app, ADMIN)
    with services.container.uow(services.workspace_id) as uow:
        box = uow.mailboxes.create("sam@quantra.example", "quantra.example")
        uow.commit()
    report = api.post(f"/api/settings/mailboxes/{box.id}/dns-check").json()
    assert report["spf"]["ok"] and report["dmarc"]["ok"] and not report["dkim"]["ok"]
    assert report["ok"] is False
    assert api.get("/api/mailboxes").json()[0]["dns_check"]["ok"] is False


# ------------------------------------------------------------------ the signed webhook


SECRET = WEBHOOK_SECRET


def signed(
    payload: dict[str, object], *, secret: str = SECRET, age: float = 0
) -> dict[str, object]:
    body = json.dumps(payload).encode()
    stamp = str(int(time.time() - age))
    digest = hmac.new(secret.encode(), stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return {
        "content": body,
        "headers": {"X-Timestamp": stamp, "X-Signature": f"sha256={digest}"},
    }


@pytest.fixture
def secret() -> None:
    """The test app is built with the webhook secret already set (see conftest)."""


def test_a_signed_webhook_creates_targets_without_a_login(
    anonymous: TestClient, secret: None, services: Services
) -> None:
    payload = {"event_id": "evt-1", "targets": [{"website": "acme.com"}, {"website": "beta.io"}]}
    response = anonymous.post("/api/intake/webhook", **signed(payload))  # type: ignore[arg-type]
    assert response.status_code == 200
    body = response.json()
    assert body["duplicate"] is False and [r["status"] for r in body["rows"]] == ["accepted"] * 2
    with services.container.uow(services.workspace_id) as uow:
        assert uow.companies.known_domains() == {"acme.com", "beta.io"}


def test_the_same_event_twice_changes_nothing(anonymous: TestClient, secret: None) -> None:
    payload = {"event_id": "evt-2", "website": "acme.com", "notes": "from the CRM"}
    first = anonymous.post("/api/intake/webhook", **signed(payload))  # type: ignore[arg-type]
    second = anonymous.post("/api/intake/webhook", **signed(payload))  # type: ignore[arg-type]
    assert first.json()["duplicate"] is False
    assert second.status_code == 200 and second.json() == {"duplicate": True}


def test_a_bad_signature_is_rejected(anonymous: TestClient, secret: None) -> None:
    request = signed({"event_id": "e", "website": "acme.com"}, secret="wrong")
    response = anonymous.post("/api/intake/webhook", **request)  # type: ignore[arg-type]
    assert response.status_code == 401 and response.json()["code"] == "bad_signature"


def test_a_tampered_body_is_rejected(anonymous: TestClient, secret: None) -> None:
    request = signed({"event_id": "e", "website": "acme.com"})
    request["content"] = b'{"event_id": "e", "website": "evil.com"}'
    response = anonymous.post("/api/intake/webhook", **request)  # type: ignore[arg-type]
    assert response.json()["code"] == "bad_signature"


def test_an_old_signed_request_is_not_replayable(anonymous: TestClient, secret: None) -> None:
    request = signed({"event_id": "e", "website": "acme.com"}, age=3_600)
    response = anonymous.post("/api/intake/webhook", **request)  # type: ignore[arg-type]
    assert response.status_code == 401 and response.json()["code"] == "stale_timestamp"


def test_missing_headers_and_a_missing_secret_are_refused(anonymous: TestClient) -> None:
    anonymous.app.state.webhook_secret = ""  # type: ignore[attr-defined]
    off = anonymous.post("/api/intake/webhook", **signed({"event_id": "e", "website": "a.com"}))  # type: ignore[arg-type]
    assert off.status_code == 503 and off.json()["code"] == "webhook_disabled"
    anonymous.app.state.webhook_secret = SECRET  # type: ignore[attr-defined]
    bare = anonymous.post("/api/intake/webhook", content=b"{}")
    assert bare.status_code == 401


def test_a_webhook_payload_needs_an_event_id_and_targets(
    anonymous: TestClient, secret: None
) -> None:
    no_id = anonymous.post("/api/intake/webhook", **signed({"website": "a.com"}))  # type: ignore[arg-type]
    assert no_id.status_code == 422 and no_id.json()["code"] == "missing_event_id"
    too_many = {"event_id": "e", "targets": [{"website": f"a{i}.com"} for i in range(201)]}
    big = anonymous.post("/api/intake/webhook", **signed(too_many))  # type: ignore[arg-type]
    assert big.json()["code"] == "bad_targets"


# ------------------------------------------------------------------ privacy


def seeded_person(factory: UnitOfWorkFactory, ws: str, domain: str = "acme.com") -> tuple[str, str]:
    """A company with one person who has a drafted email. Returns (company id, contact id)."""
    company_id, message_id = seed_review(factory, ws, domain)
    with factory(ws) as uow:
        message = uow.messages.get(message_id)
        approved = uow.messages.transition(
            message_id, MessageState.APPROVED, expected_version=message.row_version
        )
        uow.messages.transition(
            message_id,
            MessageState.DRAFTED,
            expected_version=approved.row_version,
            set_fields={"remote_draft_id": f"<{message_id}@q>"},
        )
        uow.commit()
        return company_id, message.contact_id


def test_a_person_can_be_suppressed_from_the_lead_page(
    api: Api, factory: UnitOfWorkFactory, ws: str
) -> None:
    company_id, contact_id = seeded_person(factory, ws)
    body = api.post(f"/api/contacts/{contact_id}/suppress").json()
    assert body["found"] is True and body["messages_cancelled"] == 1
    assert len(body["drafts_left"]) == 1  # no mailbox here, so the operator is told to delete it
    lead = api.get(f"/api/companies/{company_id}").json()
    assert lead["company"]["status"] == "suppressed"
    assert lead["contacts"][0]["status"] == "opted_out"
    assert lead["messages"][0]["state"] == "cancelled"


def test_a_whole_company_can_be_suppressed(api: Api, factory: UnitOfWorkFactory, ws: str) -> None:
    company_id, _ = seeded_person(factory, ws)
    assert api.post(f"/api/companies/{company_id}/suppress").status_code == 200
    assert api.get(f"/api/companies/{company_id}").json()["company"]["status"] == "suppressed"
    again = api.post("/api/targets", json={"website": "acme.com"}).json()
    assert again["rows"][0]["status"] == "rejected"  # the domain is on the list now


def test_an_erasure_request_removes_the_person_and_suppresses_the_address(
    api: Api, factory: UnitOfWorkFactory, ws: str
) -> None:
    company_id, _ = seeded_person(factory, ws)
    body = api.post("/api/privacy/forget", json={"email": "JANE@acme.com"}).json()
    assert body["found"] is True
    lead = api.get(f"/api/companies/{company_id}").json()
    assert lead["contacts"][0]["full_name"] is None
    assert lead["contacts"][0]["emails"][0]["email"] is None
    assert (
        api.post("/api/targets", json={"email": "jane@acme.com"}).json()["rows"][0]["status"]
        == "rejected"
    )


def test_an_erasure_request_for_a_stranger_still_works(api: Api) -> None:
    body = api.post("/api/privacy/forget", json={"email": "stranger@nowhere.com"}).json()
    assert body["found"] is False
    assert api.post("/api/privacy/forget", json={"email": "x"}).status_code == 422


def test_privacy_actions_need_a_login_and_an_existing_target(
    api: Api, anonymous: TestClient
) -> None:
    fresh = TestClient(anonymous.app)
    assert (
        fresh.post("/api/privacy/forget", json={"email": "a@b.com"}, headers=HEADERS).status_code
        == 401
    )
    assert api.post("/api/contacts/nope/suppress").status_code == 404
    assert api.post("/api/companies/nope/suppress").status_code == 404


def test_a_campaign_or_person_from_another_workspace_is_refused(
    api: Api, factory: UnitOfWorkFactory, ws: str, other_ws: str
) -> None:
    with factory(other_ws) as uow:
        foreign = uow.campaigns.create("theirs", ["CTO"])
        company = uow.companies.create(domain="theirs.com", source=CompanySource.MANUAL)
        contact = uow.contacts.add(company.id, rank=1, source=ContactSource.SITE)
        uow.commit()
    assert (
        api.post(
            "/api/targets", json={"website": "mine.com", "campaign_id": foreign.id}
        ).status_code
        == 404
    )
    assert api.post(f"/api/contacts/{contact.id}/suppress").status_code == 404
    assert (
        api.post(
            f"/api/contacts/{contact.id}/consents", json={"basis": "express", "evidence": "x"}
        ).status_code
        == 404
    )
    api.post("/api/targets", json={"website": "mine.com"})
    mine = api.get("/api/companies").json()["items"][0]
    stolen = api.patch(
        f"/api/companies/{mine['id']}",
        json={"row_version": mine["row_version"], "campaign_id": foreign.id},
    )
    assert stolen.status_code == 404


def test_a_delivery_that_loses_the_race_to_the_same_event_is_a_duplicate(
    services: Services, secret: None
) -> None:
    """If another delivery commits first, the database index turns ours into a clean duplicate."""
    from sqlalchemy.exc import IntegrityError

    def raced(*args: object, **kwargs: object) -> None:
        raise IntegrityError("insert", {}, Exception("unique"))

    services.webhook._intake.run = raced  # type: ignore[method-assign,assignment]
    result = services.webhook.receive({"event_id": "evt-race", "website": "acme.com"})
    assert result.duplicate is True


# ------------------------------------------------------------------ the lead journey


def stage_states(journey: dict[str, object]) -> dict[str, str]:
    stages = journey["stages"]
    assert isinstance(stages, list)
    return {s["key"]: s["state"] for s in stages}


def test_the_journey_of_a_new_lead_starts_at_research(
    api: Api, factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = seed_company(factory, ws, "acme.com")
    journey = api.get(f"/api/companies/{cid}/journey").json()
    assert journey["headline"] == "New"
    assert stage_states(journey) == {
        "intake": "done",
        "research": "current",
        "qualification": "pending",
        "people": "pending",
        "email": "pending",
        "copy": "pending",
        "review": "pending",
        "outreach": "pending",
    }
    assert journey["origin"]["how"] == "Added by an operator"


def test_the_journey_says_how_an_imported_lead_arrived(api: Api) -> None:
    api.post("/api/targets", json={"website": "https://www.acme.com", "country": "UK"})
    cid = company_id(api, "acme.com")
    origin = api.get(f"/api/companies/{cid}/journey").json()["origin"]
    labels = {f["label"]: f["value"] for f in origin["facts"]}
    assert origin["how"].startswith("Added by an operator via")
    assert "website" in labels["As supplied"] and "acme.com" in labels["Matching"]
    assert origin["by"] == "operator"


def test_a_lead_in_review_shows_each_finished_stage_and_what_it_cost(
    api: Api, factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = seed_company(
        factory, ws, "acme.com", C.RESEARCHED, C.QUALIFIED, C.CONTACTS_FOUND, C.EMAIL_READY
    )
    with factory(ws) as uow:
        contact = uow.contacts.add(cid, rank=1, source=ContactSource.SITE, full_name="Jane Doe")
        uow.emails.add(
            contact.id,
            "jane@acme.com",
            Provenance.API_DATABASE,
            is_primary=True,
            found_by="hunter",
            status=EmailStatus.VALID,
        )
        uow.calls.record(
            provider="hunter",
            operation="find",
            request_hash="h",
            outcome=CallOutcome.HIT,
            cost_micro_usd=24_500,
            company_id=cid,
        )
        company = uow.companies.get(cid)
        uow.companies.transition(
            cid, C.COPY_READY, expected_version=company.row_version, reason="copy written"
        )
        uow.commit()
    journey = api.get(f"/api/companies/{cid}/journey").json()
    assert stage_states(journey)["email"] == "done"
    assert stage_states(journey)["review"] == "waiting"
    assert "review the email" in journey["next_step"]
    by_key = {s["key"]: s for s in journey["stages"]}
    assert by_key["people"]["facts"][0]["value"].startswith("Jane Doe")
    assert "jane@acme.com" in by_key["email"]["facts"][0]["value"]
    # The call was made while the lead was working towards the stage it was recorded in.
    assert journey["total_cost_micro_usd"] == 24_500
    assert sum(s["cost_micro_usd"] for s in journey["stages"]) == 24_500


def test_a_held_lead_blocks_the_stage_that_held_it(
    api: Api, factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = seed_company(
        factory, ws, "acme.com", C.RESEARCHED, C.HELD, hold=HoldReason.COUNTRY_UNKNOWN
    )
    journey = api.get(f"/api/companies/{cid}/journey").json()
    assert journey["headline"] == "Held: country unknown"
    states = stage_states(journey)
    assert (states["research"], states["qualification"], states["people"]) == (
        "done",
        "held",
        "pending",
    )
    [incident] = {s["key"]: s for s in journey["stages"]}["qualification"]["incidents"]
    assert "country unknown" in incident["text"]


def test_failed_and_disqualified_leads_say_where_they_stopped(
    api: Api, factory: UnitOfWorkFactory, ws: str
) -> None:
    failed = seed_company(factory, ws, "a.com", C.FAILED, failed_stage="research")
    out = seed_company(factory, ws, "b.com", C.RESEARCHED, C.DISQUALIFIED)
    assert stage_states(api.get(f"/api/companies/{failed}/journey").json())["research"] == "failed"
    stopped = api.get(f"/api/companies/{out}/journey").json()
    assert stage_states(stopped)["qualification"] == "stopped"
    assert "override" in stopped["next_step"]


def test_the_journey_of_another_workspaces_lead_is_not_found(api: Api) -> None:
    assert api.get("/api/companies/nope/journey").status_code == 404


def test_a_person_added_with_consent_ends_the_consent_hold(
    api: Api, factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        uow.policies.upsert(CountryPolicy("IN", PolicyRule.CONSENT_REQUIRED))
        company = uow.companies.create(
            domain="tatapower.com", source=CompanySource.MANUAL, country_code="IN"
        )
        held = uow.companies.transition(
            company.id, C.RESEARCHED, expected_version=company.row_version
        )
        uow.companies.transition(
            company.id,
            C.HELD,
            expected_version=held.row_version,
            hold_reason=HoldReason.CONSENT_REQUIRED,
        )
        uow.commit()
    cid = company.id
    stuck = api.post(f"/api/companies/{cid}/release-hold", json={})
    assert stuck.status_code == 409 and "Add a person" in stuck.json()["detail"]

    bad = api.post(
        f"/api/companies/{cid}/people", json={"full_name": "Asha Rao", "consent_basis": "express"}
    )
    assert bad.status_code == 422 and "evidence" in bad.json()["detail"]

    added = api.post(
        f"/api/companies/{cid}/people",
        json={
            "full_name": "Asha Rao",
            "title": "Head of Strategy",
            "email": "asha@tatapower.com",
            "consent_basis": "express",
            "consent_evidence": "Asked for a demo at the 2026 summit",
        },
    )
    assert added.status_code == 201
    assert added.json()["emails"][0]["email"] == "asha@tatapower.com"
    assert api.post(f"/api/companies/{cid}/release-hold", json={}).json()["status"] == "researched"
    assert api.post("/api/companies/nope/people", json={"full_name": "Sam Lee"}).status_code == 404


def test_a_person_can_be_corrected_through_the_api(
    api: Api, factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = seed_company(factory, ws, "acme.com", C.RESEARCHED)
    with factory(ws) as uow:
        person = uow.contacts.add(cid, rank=1, source=ContactSource.OPERATOR, full_name="sonal")
        uow.commit()
    refused = api.patch(f"/api/contacts/{person.id}", json={"full_name": "sonal"})
    assert refused.status_code == 422 and "first and a last name" in refused.json()["detail"]
    fixed = api.patch(
        f"/api/contacts/{person.id}",
        json={"full_name": "Sonal Mishra", "email": "sonal@acme.com"},
    )
    assert fixed.status_code == 200
    assert fixed.json()["full_name"] == "Sonal Mishra"
    assert fixed.json()["emails"][0]["email"] == "sonal@acme.com"
    assert api.patch("/api/contacts/nope", json={"full_name": "A B"}).status_code == 404


def test_a_lead_is_deleted_only_with_its_domain_typed_and_is_then_gone(
    api: Api, factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = seed_company(factory, ws, "acme.com", C.RESEARCHED)
    with factory(ws) as uow:
        person = uow.contacts.add(cid, rank=1, source=ContactSource.OPERATOR, full_name="Sam Lee")
        uow.emails.add(person.id, "sam@acme.com", Provenance.OPERATOR_GIVEN, is_primary=True)
        uow.commit()
    wrong = api.post(f"/api/companies/{cid}/delete", json={"confirm_domain": "beta.com"})
    assert wrong.status_code == 422 and "acme.com" in wrong.json()["detail"]
    assert api.get(f"/api/companies/{cid}").status_code == 200  # still there

    done = api.post(
        f"/api/companies/{cid}/delete",
        json={"confirm_domain": "ACME.com", "also_suppress_domain": True},
    )
    assert done.status_code == 200
    assert done.json() == {
        "domain": "acme.com",
        "contacts_removed": 1,
        "messages_removed": 0,
        "drafts_deleted": 0,
        "drafts_left": [],
        "domain_suppressed": True,
    }
    assert api.get(f"/api/companies/{cid}").status_code == 404
    assert api.get("/api/companies").json()["total"] == 0
    assert (
        api.post(f"/api/companies/{cid}/delete", json={"confirm_domain": "acme.com"}).status_code
        == 404
    )


def test_a_lead_that_was_emailed_cannot_be_deleted_through_the_api(
    api: Api, factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = seed_company(factory, ws, "sent.com", C.RESEARCHED)
    with factory(ws) as uow:
        person = uow.contacts.add(cid, rank=1, source=ContactSource.OPERATOR, full_name="A B")
        address = uow.emails.add(
            person.id, "a@sent.com", Provenance.OPERATOR_GIVEN, is_primary=True
        )
        message = uow.messages.create(
            company_id=cid,
            contact_id=person.id,
            contact_email_id=address.id,
            step=0,
            subject="hello",
            generated_body="hi",
            state=MessageState.APPROVED,
        )
        message = uow.messages.transition(
            message.id, MessageState.SENT, expected_version=message.row_version
        )
        uow.commit()
    response = api.post(f"/api/companies/{cid}/delete", json={"confirm_domain": "sent.com"})
    assert response.status_code == 409 and "Suppress" in response.json()["detail"]
    assert api.get(f"/api/companies/{cid}").status_code == 200


def test_the_email_can_go_to_someone_else_and_a_wrong_match_be_removed(
    api: Api, factory: UnitOfWorkFactory, ws: str
) -> None:
    cid, mid = seed_review(factory, ws)
    with factory(ws) as uow:
        other = uow.contacts.add(cid, rank=2, source=ContactSource.SITE, full_name="Sam Lee")
        wrong = uow.contacts.add(cid, rank=3, source=ContactSource.SEARCH, full_name="Dan Roth")
        uow.commit()
    moved = api.post(f"/api/companies/{cid}/change-recipient", json={"contact_id": other.id})
    assert moved.status_code == 200 and moved.json()["status"] == "contacts_found"
    lead = api.get(f"/api/companies/{cid}").json()
    assert lead["contacts"][0]["id"] == other.id
    assert [m["state"] for m in lead["messages"] if m["id"] == mid] == ["cancelled"]

    assert api.delete(f"/api/contacts/{wrong.id}").status_code == 204
    assert wrong.id not in [c["id"] for c in api.get(f"/api/companies/{cid}").json()["contacts"]]
    written_to = api.get(f"/api/companies/{cid}").json()["messages"][0]["contact_id"]
    refused = api.delete(f"/api/contacts/{written_to}")
    assert refused.status_code in (409, 422) and "already been written" in refused.json()["detail"]


def test_the_country_rule_can_be_skipped_for_a_lead_and_switched_off_for_the_workspace(
    api: Api, factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = seed_company(factory, ws, "acme.com", C.RESEARCHED, C.QUALIFIED)
    refused = api.post(f"/api/companies/{cid}/policy-skip", json={"from_stage": "later"})
    assert refused.status_code == 422
    skipped = api.post(
        f"/api/companies/{cid}/policy-skip", json={"from_stage": "contacts", "reason": "known"}
    )
    assert skipped.status_code == 200 and skipped.json()["policy_skip_from"] == "contacts"
    assert api.get(f"/api/companies/{cid}").json()["company"]["policy_skip_from"] == "contacts"
    assert api.delete(f"/api/companies/{cid}/policy-skip").json()["policy_skip_from"] is None

    off = api.put("/api/settings/workspace", json={"country_policy_enabled": False})
    assert off.status_code == 200 and off.json()["country_policy_enabled"] is False
    assert api.post("/api/companies/release-policy-holds").json() == {"released": 0}
    assert api.put("/api/settings/workspace", json={"footer_enabled": False}).status_code == 200

    assert api.put("/api/settings/policies/SE", json={"rule": "block"}).status_code == 200
    assert api.delete("/api/settings/policies/SE").status_code == 204
    assert api.delete("/api/settings/policies/SE").status_code == 404


def test_dated_news_is_shown_on_the_lead_and_in_its_journey(
    api: Api, factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = seed_company(factory, ws, "acme.com", C.RESEARCHED)
    item = {
        "date": "2026-10-10",
        "headline": "Acme wins Leeds contract",
        "detail": "A three-year deal.",
        "matters": "",
        "url": "https://news.example.com/acme",
    }
    with factory(ws) as uow:
        current = uow.companies.get(cid)
        uow.companies.update_fields(
            cid,
            {"research": {"summary": "Acme", "news_items": [item], "triggers": []}},
            actor="system",
            expected_version=current.row_version,
        )
        uow.commit()
    assert api.get(f"/api/companies/{cid}").json()["company"]["research"]["news_items"] == [item]
    research = next(
        s
        for s in api.get(f"/api/companies/{cid}/journey").json()["stages"]
        if s["key"] == "research"
    )
    assert {
        "label": "Recent company news",
        "value": "2026-10-10 · Acme wins Leeds contract (https://news.example.com/acme)",
    } in research["facts"]


def test_an_email_can_be_thrown_away_and_written_again_to_the_same_person(
    api: Api, factory: UnitOfWorkFactory, ws: str
) -> None:
    cid, mid = seed_review(factory, ws)
    moved = api.post(f"/api/review/{mid}/rewrite")
    assert moved.status_code == 200 and moved.json()["status"] == "contacts_found"
    assert api.get("/api/review").json() == []  # nothing is waiting for review any more
    lead = api.get(f"/api/companies/{cid}").json()
    assert [m["state"] for m in lead["messages"]] == ["cancelled"]
    assert lead["contacts"][0]["full_name"] == "Jane Doe"  # still the same person
    unknown = api.post("/api/review/nope/rewrite")
    assert unknown.status_code == 409 and "no message" in unknown.json()["detail"]


def test_email_length_greeting_and_past_emails_are_settings_with_limits(api: Api) -> None:
    ok = api.put("/api/settings/workspace", json={"email_min_words": 100, "email_max_words": 150})
    assert ok.status_code == 200 and ok.json()["email_max_words"] == 150
    backwards = api.put("/api/settings/workspace", json={"email_min_words": 400})
    assert backwards.status_code == 422 and "cannot be longer" in backwards.json()["detail"]
    assert api.put("/api/settings/workspace", json={"email_max_words": 5000}).status_code == 422

    profile = api.put(
        "/api/settings/sender-profile",
        json={
            "greeting": "Dear",
            "outreach_goal": "a partnership",
            "style_examples": ["Dear Ted, hi."],
        },
    )
    assert profile.status_code == 200 and profile.json()["greeting"] == "Dear"
    assert api.put("/api/settings/sender-profile", json={"greeting": "Yo"}).status_code == 422
    too_many = api.put("/api/settings/sender-profile", json={"style_examples": ["x"] * 7})
    assert too_many.status_code == 422


def test_a_runs_leads_and_research_again_through_the_api(
    api: Api, factory: UnitOfWorkFactory, ws: str
) -> None:
    run = api.post("/api/runs", json={}).json()
    assert api.get(f"/api/runs/{run['id']}/leads").json() == []
    assert api.get("/api/runs/nope/leads").status_code == 404
    cid = seed_company(factory, ws, "acme.com", C.RESEARCHED, C.QUALIFIED)
    again = api.post(f"/api/companies/{cid}/research-again")
    assert again.status_code == 200 and again.json()["status"] == "new"
    refused = api.post(f"/api/companies/{cid}/research-again")
    assert refused.status_code in (409, 422) and "not been researched" in refused.json()["detail"]


def test_the_operator_can_ask_for_an_email_to_be_rewritten(
    api: Api, factory: UnitOfWorkFactory, ws: str
) -> None:
    _, mid = seed_review(factory, ws)
    revised = api.post(f"/api/review/{mid}/revise", json={"instructions": "More formal, please."})
    assert revised.status_code == 200
    data = revised.json()
    assert data["body"].startswith("Dear Jane,") and data["body"].endswith(FOOTER)
    assert "word_count" in data["lint_report"]
    assert api.post(f"/api/review/{mid}/revise", json={"instructions": ""}).status_code == 422
