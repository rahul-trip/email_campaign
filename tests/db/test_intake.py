"""Stage 1: every anchor type and every intake rule."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import openpyxl
import pytest

from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import (
    CompanySource,
    CompanyStatus,
    ContactStatus,
    EntityType,
    ImportAnchor,
    ImportRowStatus,
    ImportSource,
    Provenance,
    SuppressionKind,
    SuppressionReason,
)
from outbound.providers.errors import ProviderError
from outbound.providers.ports import PageText, SearchHit
from outbound.services.intake import (
    IntakeReport,
    IntakeService,
    RowOutcome,
    detect_anchor,
    discover_rows,
    load_rows,
    match_confidence,
    parse_target,
)

R = ImportRowStatus


class FakeSearch:
    name = "fake"

    def __init__(
        self, answers: dict[str, list[SearchHit]] | None = None, fail: bool = False
    ) -> None:
        self.queries: list[str] = []
        self._answers = answers or {}
        self._fail = fail

    def search(self, query: str, *, max_results: int = 5) -> list[SearchHit]:
        self.queries.append(query)
        if self._fail:
            raise ProviderError("fake", "down")
        for needle, hits in self._answers.items():
            if needle.lower() in query.lower():
                return hits
        return []

    def extract(self, urls: list[str]) -> list[PageText]:
        return []


def hit(url: str, title: str = "", snippet: str = "") -> SearchHit:
    return SearchHit(url=url, title=title, snippet=snippet)


def service(
    factory: UnitOfWorkFactory,
    ws: str,
    search: FakeSearch | None = None,
    **kwargs: Any,
) -> IntakeService:
    return IntakeService(factory, ws, search, **kwargs)


def one(report: IntakeReport) -> RowOutcome:
    assert len(report.rows) == 1
    return report.rows[0]


# ------------------------------------------------------------------ reading rows


def test_headers_are_matched_loosely() -> None:
    target = parse_target(
        {
            "Organization URL": "https://acme.com",
            "Direct Business Email": "jane@acme.com",
            "Specific Person to Contact": "Jane Doe",
            "Country": "United Kingdom",
            "Notes": "met at expo",
            "Priority": "2",
            "Something Else": "ignored",
        }
    )
    assert (target.website, target.email, target.person) == (
        "https://acme.com",
        "jane@acme.com",
        "Jane Doe",
    )
    assert (target.country, target.notes, target.priority) == ("United Kingdom", "met at expo", 2)


def test_an_unusable_priority_is_ignored() -> None:
    assert parse_target({"company": "Acme", "priority": "urgent"}).priority is None
    assert parse_target({"company": "Acme", "priority": "12"}).priority is None


@pytest.mark.parametrize(
    ("row", "anchor"),
    [
        ({"website": "https://www.acme.co.uk/about"}, ImportAnchor.DOMAIN),
        ({"email": "jane@acme.com"}, ImportAnchor.EMAIL),
        ({"linkedin": "https://www.linkedin.com/in/jane-doe-123"}, ImportAnchor.LINKEDIN_URL),
        ({"person": "Jane Doe", "company": "Acme"}, ImportAnchor.PERSON_COMPANY),
        ({"company": "Acme"}, ImportAnchor.COMPANY_NAME),
        ({"website": "https://acme.com", "company": "Acme"}, ImportAnchor.DOMAIN),
        (
            {"linkedin": "https://linkedin.com/in/jane", "company": "Acme"},
            ImportAnchor.COMPANY_NAME,
        ),
        ({"email": "jane@gmail.com", "company": "Acme"}, ImportAnchor.COMPANY_NAME),
        ({"email": "jane@gmail.com"}, None),
        ({"person": "Jane Doe"}, None),
        ({}, None),
    ],
)
def test_the_anchor_is_chosen_from_what_the_operator_gave(
    row: dict[str, str], anchor: ImportAnchor | None
) -> None:
    assert detect_anchor(parse_target(row)) == anchor


def test_csv_files_with_any_delimiter_and_a_bom_are_read(tmp_path: Path) -> None:
    path = tmp_path / "targets.csv"
    path.write_text("﻿Company;Website\nAcme;acme.com\n;\nBeta;beta.io\n", encoding="utf-8")
    assert load_rows(path) == [
        {"Company": "Acme", "Website": "acme.com"},
        {"Company": "Beta", "Website": "beta.io"},
    ]


def test_xlsx_files_are_read_and_blank_rows_skipped(tmp_path: Path) -> None:
    path = tmp_path / "targets.xlsx"
    book = openpyxl.Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.append(["Company", "Website"])
    sheet.append(["Acme", "acme.com"])
    sheet.append([None, None])
    book.save(path)
    assert load_rows(path) == [{"Company": "Acme", "Website": "acme.com"}]


def test_other_file_types_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"csv or \.xlsx"):
        load_rows(tmp_path / "targets.pdf")


# ------------------------------------------------------------------ domain anchor


def test_a_website_becomes_a_company_at_new_with_the_root_domain(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    report = service(factory, ws).run([{"Website": "https://www.Acme.co.uk/about?x=1"}])
    outcome = one(report)
    assert (outcome.status, outcome.domain) == (R.ACCEPTED, "acme.co.uk")
    with factory(ws) as uow:
        company = uow.companies.by_domain("acme.co.uk")
        assert company is not None
        assert (company.status, company.source) == (CompanyStatus.NEW, CompanySource.MANUAL)


def test_what_the_operator_typed_is_protected_from_the_engine(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    service(factory, ws).run(
        [{"Company": "Acme Energy", "Website": "acme.com", "Country": "UK", "Priority": "1"}]
    )
    with factory(ws) as uow:
        company = uow.companies.by_domain("acme.com")
        assert company is not None
        assert (company.name, company.country_code, company.priority) == ("Acme Energy", "GB", 1)
        assert set(company.manual_fields) == {"name", "country_code", "priority"}


def test_notes_a_person_and_an_address_come_with_the_row(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    service(factory, ws).run(
        [
            {
                "Website": "acme.com",
                "Person": "Jane Doe\n(CTO)",
                "Email": "Jane@Acme.com",
                "Notes": "met at the expo",
            }
        ]
    )
    with factory(ws) as uow:
        company = uow.companies.by_domain("acme.com")
        assert company is not None
        [contact] = uow.contacts.for_company(company.id)
        assert (contact.full_name, contact.title, contact.rank) == ("Jane Doe", "CTO", 1)
        assert contact.status is ContactStatus.ACTIVE
        [address] = uow.emails.for_contact(contact.id)
        assert (address.email, address.provenance, address.is_primary) == (
            "jane@acme.com",
            Provenance.OPERATOR_GIVEN,
            True,
        )
        assert [n.body for n in uow.notes.for_company(company.id)] == ["met at the expo"]


# ------------------------------------------------------------------ email anchor


def test_the_domain_is_taken_from_a_work_email(factory: UnitOfWorkFactory, ws: str) -> None:
    search = FakeSearch()
    outcome = one(service(factory, ws, search).run([{"Email": "jane@acme.com"}]))
    assert (outcome.status, outcome.domain) == (R.ACCEPTED, "acme.com")
    assert search.queries == []  # no paid search when the address says it all
    with factory(ws) as uow:
        company = uow.companies.by_domain("acme.com")
        assert company is not None
        [contact] = uow.contacts.for_company(company.id)
        assert uow.emails.for_contact(contact.id)[0].email == "jane@acme.com"


def test_a_free_mail_address_alone_is_rejected(factory: UnitOfWorkFactory, ws: str) -> None:
    outcome = one(service(factory, ws).run([{"Email": "jane@gmail.com"}]))
    assert outcome.status is R.REJECTED
    assert "free-mail" in (outcome.reason or "")


def test_a_free_mail_address_with_a_company_resolves_by_name_and_drops_the_address(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    search = FakeSearch({"Acme": [hit("https://acme.com", "Acme")]})
    outcome = one(
        service(factory, ws, search).run([{"Company": "Acme", "Email": "jane@gmail.com"}])
    )
    assert outcome.status is R.ACCEPTED
    assert "free-mail address ignored" in (outcome.reason or "")
    with factory(ws) as uow:
        assert uow.emails.by_address("jane@gmail.com") is None


def test_a_free_mail_address_is_kept_when_the_operator_allows_personal_domains(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    search = FakeSearch({"Acme": [hit("https://acme.com", "Acme")]})
    service(factory, ws, search, allow_personal_domain=True).run(
        [{"Company": "Acme", "Email": "jane@gmail.com"}]
    )
    with factory(ws) as uow:
        assert uow.emails.by_address("jane@gmail.com") is not None


# ------------------------------------------------------------------ company-name anchor


def test_a_company_name_is_resolved_with_one_search(factory: UnitOfWorkFactory, ws: str) -> None:
    search = FakeSearch(
        {
            "Acme Energy": [
                hit("https://www.linkedin.com/company/acme", "Acme Energy | LinkedIn"),
                hit("https://acmeenergy.com/", "Acme Energy - Home"),
            ]
        }
    )
    report = service(factory, ws, search).run([{"Company": "Acme Energy Ltd", "Country": "GB"}])
    outcome = one(report)
    assert (outcome.status, outcome.domain) == (R.ACCEPTED, "acmeenergy.com")
    assert len(search.queries) == 1
    assert "GB" in search.queries[0]


def test_a_weak_match_waits_for_the_operator(factory: UnitOfWorkFactory, ws: str) -> None:
    search = FakeSearch({"Acme": [hit("https://unrelated.com", "Totally different")]})
    report = service(factory, ws, search).run([{"Company": "Acme"}])
    outcome = one(report)
    assert (outcome.status, outcome.domain) == (R.NEEDS_CONFIRMATION, "unrelated.com")
    with factory(ws) as uow:
        assert uow.companies.by_domain("unrelated.com") is None


def test_a_name_that_matches_the_page_text_is_only_medium_confidence(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    confidence = match_confidence(
        "Acme Energy", "powerco.com", hit("https://powerco.com", "Acme Energy is now Powerco")
    )
    assert 0.5 < confidence < 0.8


def test_confirming_a_waiting_row_creates_the_company_with_the_given_domain(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    search = FakeSearch({"Acme": [hit("https://unrelated.com", "Totally different")]})
    svc = service(factory, ws, search)
    first = one(svc.run([{"Company": "Acme", "Notes": "warm intro"}]))
    assert first.row_id is not None
    [waiting] = svc.needing_confirmation()
    assert waiting.id == first.row_id

    outcome = svc.confirm(first.row_id, "https://www.acme-energy.co.uk/home")
    assert (outcome.status, outcome.domain) == (R.ACCEPTED, "acme-energy.co.uk")
    assert svc.needing_confirmation() == []
    with factory(ws) as uow:
        company = uow.companies.by_domain("acme-energy.co.uk")
        assert company is not None
        assert uow.imports.get_row(first.row_id).company_id == company.id
        assert [n.body for n in uow.notes.for_company(company.id)] == ["warm intro"]


def test_only_a_waiting_row_can_be_confirmed(factory: UnitOfWorkFactory, ws: str) -> None:
    svc = service(factory, ws)
    done = one(svc.run([{"Website": "acme.com"}]))
    assert done.row_id is not None
    with pytest.raises(ValueError, match="not waiting"):
        svc.confirm(done.row_id, "acme.com")


def test_a_nonsense_confirmation_is_refused(factory: UnitOfWorkFactory, ws: str) -> None:
    search = FakeSearch({"Acme": [hit("https://unrelated.com", "other")]})
    svc = service(factory, ws, search)
    row_id = one(svc.run([{"Company": "Acme"}])).row_id
    assert row_id is not None
    with pytest.raises(ValueError, match="usable domain"):
        svc.confirm(row_id, "not a domain")


def test_no_result_at_all_also_waits_for_the_operator(factory: UnitOfWorkFactory, ws: str) -> None:
    outcome = one(service(factory, ws, FakeSearch()).run([{"Company": "Nobody Inc"}]))
    assert (outcome.status, outcome.domain) == (R.NEEDS_CONFIRMATION, None)
    assert "no website found" in (outcome.reason or "")


def test_a_failed_search_waits_instead_of_losing_the_row(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    outcome = one(service(factory, ws, FakeSearch(fail=True)).run([{"Company": "Acme"}]))
    assert outcome.status is R.NEEDS_CONFIRMATION
    assert "search failed" in (outcome.reason or "")


def test_without_a_search_provider_name_rows_wait(factory: UnitOfWorkFactory, ws: str) -> None:
    outcome = one(service(factory, ws, None).run([{"Company": "Acme"}]))
    assert outcome.status is R.NEEDS_CONFIRMATION
    assert "TAVILY_API_KEY" in (outcome.reason or "")


def test_a_search_that_only_finds_platforms_does_not_pick_one(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    search = FakeSearch(
        {"Acme": [hit("https://linkedin.com/company/acme"), hit("https://x.com/acme")]}
    )
    outcome = one(service(factory, ws, search).run([{"Company": "Acme"}]))
    assert outcome.domain is None


# ------------------------------------------------------------------ person + company, LinkedIn


def test_a_person_with_a_company_is_stored_at_rank_one(factory: UnitOfWorkFactory, ws: str) -> None:
    search = FakeSearch({"Acme": [hit("https://acme.com", "Acme")]})
    outcome = one(
        service(factory, ws, search).run(
            [{"Person": "Jane Doe", "Company": "Acme", "Title": "CTO"}]
        )
    )
    assert outcome.status is R.ACCEPTED
    with factory(ws) as uow:
        company = uow.companies.by_domain("acme.com")
        assert company is not None
        [contact] = uow.contacts.for_company(company.id)
        assert (contact.full_name, contact.title, contact.rank) == ("Jane Doe", "CTO", 1)


def test_a_linkedin_profile_is_identified_by_a_public_search_and_never_fetched(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    search = FakeSearch(
        {
            "jane doe 123": [
                hit(
                    "https://uk.linkedin.com/in/jane-doe-123",
                    "Jane Doe - CTO - Acme Energy | LinkedIn",
                )
            ],
            "Acme Energy": [hit("https://acmeenergy.com", "Acme Energy")],
        }
    )
    outcome = one(
        service(factory, ws, search).run(
            [{"LinkedIn": "https://www.linkedin.com/in/jane-doe-123/"}]
        )
    )
    assert (outcome.status, outcome.domain) == (R.ACCEPTED, "acmeenergy.com")
    assert search.queries[0].startswith("site:linkedin.com/in")
    with factory(ws) as uow:
        company = uow.companies.by_domain("acmeenergy.com")
        assert company is not None
        assert company.name == "Acme Energy"
        [contact] = uow.contacts.for_company(company.id)
        assert (contact.full_name, contact.title) == ("Jane Doe", "CTO")
        assert contact.linkedin_url == "https://www.linkedin.com/in/jane-doe-123"


def test_a_profile_that_names_no_company_waits(factory: UnitOfWorkFactory, ws: str) -> None:
    search = FakeSearch({"jane": [hit("https://linkedin.com/in/jane", "Jane | LinkedIn")]})
    outcome = one(service(factory, ws, search).run([{"LinkedIn": "https://linkedin.com/in/jane"}]))
    assert outcome.status is R.NEEDS_CONFIRMATION


# ------------------------------------------------------------------ rules


def test_a_platform_domain_is_rejected(factory: UnitOfWorkFactory, ws: str) -> None:
    outcome = one(service(factory, ws).run([{"Website": "https://www.linkedin.com/company/acme"}]))
    assert outcome.status is R.REJECTED
    assert "platform" in (outcome.reason or "")


def test_a_row_with_no_anchor_is_rejected_with_a_reason(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    outcome = one(service(factory, ws).run([{"Notes": "call them"}]))
    assert outcome.status is R.REJECTED
    assert "go on" in (outcome.reason or "")


def test_a_suppressed_domain_is_never_imported(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        uow.suppressions.add(SuppressionKind.DOMAIN, "optout.com", SuppressionReason.OPT_OUT)
        uow.commit()
    outcome = one(service(factory, ws).run([{"Website": "https://www.optout.com"}]))
    assert outcome.status is R.REJECTED
    assert "suppressed" in (outcome.reason or "")
    with factory(ws) as uow:
        assert uow.companies.by_domain("optout.com") is None


def test_a_suppressed_email_is_never_imported_even_on_a_new_domain(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        uow.suppressions.add(SuppressionKind.EMAIL, "jane@acme.com", SuppressionReason.OPT_OUT)
        uow.commit()
    outcome = one(service(factory, ws).run([{"Email": "jane@acme.com"}]))
    assert outcome.status is R.REJECTED


def test_a_duplicate_inside_one_file_is_merged_and_its_notes_kept(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    report = service(factory, ws).run(
        [
            {"Website": "acme.com", "Notes": "first"},
            {"Website": "https://www.acme.com/team", "Notes": "second"},
        ]
    )
    assert [o.status for o in report.rows] == [R.ACCEPTED, R.MERGED]
    with factory(ws) as uow:
        company = uow.companies.by_domain("acme.com")
        assert company is not None
        assert [n.body for n in uow.notes.for_company(company.id)] == ["first", "second"]


def test_an_already_contacted_domain_is_merged_not_restarted(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        existing = uow.companies.create(
            domain="acme.com", source=CompanySource.MANUAL, status=CompanyStatus.IN_SEQUENCE
        )
        uow.commit()
    outcome = one(service(factory, ws).run([{"Website": "acme.com", "Notes": "again"}]))
    assert (outcome.status, outcome.reason) == (R.MERGED, "already a target")
    with factory(ws) as uow:
        assert uow.companies.get(existing.id).status is CompanyStatus.IN_SEQUENCE
        assert [n.body for n in uow.notes.for_company(existing.id)] == ["again"]


def test_differing_values_on_a_merge_become_an_event_not_an_overwrite(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    svc = service(factory, ws)
    svc.run([{"Company": "Acme Energy", "Website": "acme.com", "Country": "GB"}])
    svc.run([{"Company": "Acme Power", "Website": "acme.com", "Country": "DE"}])
    with factory(ws) as uow:
        company = uow.companies.by_domain("acme.com")
        assert company is not None
        assert (company.name, company.country_code) == ("Acme Energy", "GB")
        merged = [
            e
            for e in uow.events.for_entity(EntityType.COMPANY, company.id)
            if e.type == "intake_merged"
        ]
        assert merged[-1].data["conflicts"] == {
            "name": {"existing": "Acme Energy", "offered": "Acme Power"},
            "country_code": {"existing": "GB", "offered": "DE"},
        }


def test_an_address_that_belongs_to_another_contact_is_not_added_twice(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    svc = service(factory, ws)
    svc.run([{"Website": "acme.com", "Email": "jane@acme.com"}])
    outcome = one(svc.run([{"Website": "other.com", "Email": "jane@acme.com"}]))
    assert "already belongs" in (outcome.reason or "")


# ------------------------------------------------------------------ batches and validation


def test_every_row_is_kept_exactly_as_supplied_with_its_outcome(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    rows = [{"Website": "acme.com", "Odd Column": "keep me"}, {"Notes": "no anchor"}]
    report = service(factory, ws).run(rows, source=ImportSource.CSV, filename="targets.csv")
    assert report.batch_id is not None
    with factory(ws) as uow:
        stored = uow.imports.get_row(report.rows[0].row_id or "")
        assert stored.raw == rows[0]
        assert stored.row_number == 2
        assert uow.imports.row_statuses(report.batch_id) == [R.ACCEPTED, R.REJECTED]


def test_validate_only_reports_everything_and_writes_nothing(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    search = FakeSearch()
    report = service(factory, ws, search).run(
        [
            {"Website": "acme.com"},
            {"Website": "acme.com"},
            {"Company": "Needs Search"},
            {"Website": "linkedin.com/company/x"},
        ],
        validate_only=True,
    )
    assert [o.status for o in report.rows] == [R.ACCEPTED, R.MERGED, R.PENDING, R.REJECTED]
    assert report.batch_id is None
    assert search.queries == []
    with factory(ws) as uow:
        assert uow.companies.known_domains() == set()
        assert uow.imports.rows_with_status(R.ACCEPTED) == []


def test_running_the_same_file_twice_creates_nothing_new(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    rows = [{"Website": "acme.com"}, {"Website": "beta.io"}]
    svc = service(factory, ws)
    svc.run(rows)
    second = svc.run(rows)
    assert [o.status for o in second.rows] == [R.MERGED, R.MERGED]
    with factory(ws) as uow:
        assert uow.companies.known_domains() == {"acme.com", "beta.io"}


def test_a_campaign_is_attached_to_every_company(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        campaign = uow.campaigns.create("expo", ["CTO"])
        uow.commit()
    service(factory, ws).run([{"Website": "acme.com"}], campaign_id=campaign.id)
    with factory(ws) as uow:
        company = uow.companies.by_domain("acme.com")
        assert company is not None
        assert company.campaign_id == campaign.id


def test_discovery_rows_are_websites_only_and_skip_platforms_and_repeats() -> None:
    search = FakeSearch(
        {
            "grid": [
                hit("https://acme.com/a", "Acme | Home"),
                hit("https://acme.com/b", "Acme again"),
                hit("https://linkedin.com/company/x", "X"),
                hit("https://beta.io", "Beta"),
            ]
        }
    )
    assert discover_rows(search, ["grid software"]) == [
        {"website": "acme.com", "company": "Acme"},
        {"website": "beta.io", "company": "Beta"},
    ]


def test_discovered_companies_are_marked_as_discovered_and_not_operator_chosen(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    service(factory, ws).run(
        [{"website": "acme.com", "company": "Acme"}], company_source=CompanySource.DISCOVERY
    )
    with factory(ws) as uow:
        company = uow.companies.by_domain("acme.com")
        assert company is not None
        assert company.source is CompanySource.DISCOVERY
        assert company.name == "Acme"
        assert company.manual_fields == ()


def test_csv_round_trip_through_the_service(
    factory: UnitOfWorkFactory, ws: str, tmp_path: Path
) -> None:
    path = tmp_path / "t.csv"
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Organization URL", "Direct Business Email"])
        writer.writerow(["https://acme.com", "jane@acme.com"])
    report = service(factory, ws).run(load_rows(path), source=ImportSource.CSV, filename=path.name)
    assert report.count(R.ACCEPTED) == 1
