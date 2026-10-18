from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest
from sqlalchemy import text

from outbound.db.uow import UnitOfWork, UnitOfWorkFactory
from outbound.domain.enums import (
    CompanySource,
    CompanyStatus,
    ContactStatus,
    EntityType,
    ImportRowStatus,
    MessageState,
    Provenance,
)
from outbound.domain.names import split_name, split_person
from outbound.services.legacy_import import (
    COLUMNS,
    LegacyWorkbookError,
    import_legacy_xlsx,
    split_organisation,
)

REAL_WORKBOOK = Path(__file__).parents[2] / "Quantra_Energy_Outbound_Campaign_Matrix.xlsx"


def make_workbook(tmp_path: Path, rows: list[list[str]], header: list[str] | None = None) -> Path:
    book = openpyxl.Workbook()
    sheet = book.worksheets[0]
    sheet.append(header or list(COLUMNS))
    for row in rows:
        sheet.append(row)
    path = tmp_path / "legacy.xlsx"
    book.save(path)
    return path


def row(org: str, person: str, email: str, pitch: str = "Hi there") -> list[str]:
    return [org, person, "likes sailing", email, pitch, "follow up text", "- common ground"]


def counts(uow: UnitOfWork) -> dict[str, int]:
    return {
        table: int(uow.session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0)
        for table in ("companies", "contacts", "contact_emails", "messages", "notes", "import_rows")
    }


# ------------------------------------------------------------------ the real workbook (the gate)


@pytest.mark.skipif(
    not REAL_WORKBOOK.exists(), reason="the legacy workbook is not in this checkout"
)
def test_the_ten_real_leads_import_as_already_contacted(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    result = import_legacy_xlsx(factory, ws, REAL_WORKBOOK)
    assert (result.read, result.imported, result.merged, result.rejected) == (10, 10, 0, 0)
    with factory(ws) as uow:
        assert counts(uow) == {
            "companies": 10, "contacts": 10, "contact_emails": 10,
            "messages": 10, "notes": 10, "import_rows": 10,
        }  # fmt: skip
        assert "openclimatefix.org" in uow.companies.known_domains()
        company = uow.companies.by_domain("openclimatefix.org")
        assert company is not None
        assert (company.status, company.source) == (CompanyStatus.COMPLETED, CompanySource.IMPORT)
        assert company.name == "Open Climate Fix"
        (contact,) = uow.contacts.for_company(company.id)
        assert (contact.full_name, contact.title, contact.status) == (
            "Jack Kelly", "Co-Founder & Lead Researcher", ContactStatus.ACTIVE,
        )  # fmt: skip
        (address,) = uow.emails.for_contact(contact.id)
        assert (address.email, address.provenance, address.is_primary) == (
            "jack@openclimatefix.org", Provenance.OPERATOR_GIVEN, True,
        )  # fmt: skip
        (message,) = uow.messages.for_company(company.id)
        assert message.state is MessageState.DRAFTED and message.step == 0
        assert message.generated_body.startswith("Dear Jack")


@pytest.mark.skipif(
    not REAL_WORKBOOK.exists(), reason="the legacy workbook is not in this checkout"
)
def test_importing_the_real_workbook_again_changes_nothing(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    import_legacy_xlsx(factory, ws, REAL_WORKBOOK)
    with factory(ws) as uow:
        before = counts(uow)
    second = import_legacy_xlsx(factory, ws, REAL_WORKBOOK)
    assert (second.imported, second.merged, second.rejected) == (0, 10, 0)
    with factory(ws) as uow:
        after = counts(uow)
    assert after["companies"] == before["companies"] == 10
    assert after["messages"] == before["messages"] == 10
    assert (
        after["import_rows"] == before["import_rows"] + 10
    )  # the second batch is kept as an audit


@pytest.mark.skipif(
    not REAL_WORKBOOK.exists(), reason="the legacy workbook is not in this checkout"
)
def test_the_whole_sheet_row_is_kept_in_the_import_row(factory: UnitOfWorkFactory, ws: str) -> None:
    import_legacy_xlsx(factory, ws, REAL_WORKBOOK)
    with factory(ws) as uow:
        raw = uow.session.execute(text("SELECT raw FROM import_rows WHERE row_number = 2")).scalar()
    assert "Follow-up Text" in str(raw) and "Points of Commonality" in str(raw)


# ------------------------------------------------------------------ edge cases


def test_a_company_is_recorded_with_an_import_event(
    factory: UnitOfWorkFactory, ws: str, tmp_path: Path
) -> None:
    path = make_workbook(
        tmp_path, [row("Acme\nhttps://www.acme.com/about", "Jane Doe\n(CTO)", "jane@acme.com")]
    )
    import_legacy_xlsx(factory, ws, path)
    with factory(ws) as uow:
        company = uow.companies.by_domain("acme.com")
        assert company is not None
        event = [
            e
            for e in uow.events.for_entity(EntityType.COMPANY, company.id)
            if e.type == "legacy_imported"
        ]
        assert event[0].data == {"file": "legacy.xlsx", "sheet_row": 2}


def test_a_row_with_no_website_uses_the_email_domain(
    factory: UnitOfWorkFactory, ws: str, tmp_path: Path
) -> None:
    path = make_workbook(tmp_path, [row("Acme", "Jane Doe", "jane@acme.com")])
    result = import_legacy_xlsx(factory, ws, path)
    assert result.imported == 1
    with factory(ws) as uow:
        assert uow.companies.by_domain("acme.com") is not None


def test_a_row_with_neither_website_nor_email_is_rejected_with_a_reason(
    factory: UnitOfWorkFactory, ws: str, tmp_path: Path
) -> None:
    path = make_workbook(tmp_path, [row("Nameless Ltd", "Jane Doe", "")])
    result = import_legacy_xlsx(factory, ws, path)
    assert (result.imported, result.rejected) == (0, 1)
    with factory(ws) as uow:
        assert counts(uow)["companies"] == 0
        reasons = uow.session.execute(text("SELECT status, reason FROM import_rows")).all()
        assert reasons == [("rejected", "no usable website or email domain")]


def test_two_rows_for_one_domain_make_one_company(
    factory: UnitOfWorkFactory, ws: str, tmp_path: Path
) -> None:
    path = make_workbook(
        tmp_path,
        [
            row("Acme\nhttps://acme.com/a", "Jane Doe", "jane@acme.com"),
            row("Acme again\nhttps://www.acme.com/b", "Sam Roe", "sam@acme.com"),
        ],
    )
    result = import_legacy_xlsx(factory, ws, path)
    assert (result.imported, result.merged) == (1, 1)


def test_an_address_already_used_elsewhere_skips_only_the_message(
    factory: UnitOfWorkFactory, ws: str, tmp_path: Path
) -> None:
    path = make_workbook(
        tmp_path,
        [
            row("Acme\nhttps://acme.com", "Jane Doe", "shared@acme.com"),
            row("Beta\nhttps://beta.io", "Sam Roe", "shared@acme.com"),
        ],
    )
    result = import_legacy_xlsx(factory, ws, path)
    assert result.imported == 2
    with factory(ws) as uow:
        counts_now = counts(uow)
        assert counts_now["companies"] == 2 and counts_now["contact_emails"] == 1
        assert counts_now["messages"] == 1
        reason = uow.session.execute(
            text("SELECT reason FROM import_rows WHERE resolved_domain = 'beta.io'")
        ).scalar()
        assert "already belongs" in str(reason)


def test_a_row_with_no_pitch_creates_the_lead_but_no_message(
    factory: UnitOfWorkFactory, ws: str, tmp_path: Path
) -> None:
    path = make_workbook(
        tmp_path, [row("Acme\nhttps://acme.com", "Jane Doe", "jane@acme.com", pitch="")]
    )
    import_legacy_xlsx(factory, ws, path)
    with factory(ws) as uow:
        assert (
            counts(uow)["companies"],
            counts(uow)["messages"],
            counts(uow)["contact_emails"],
        ) == (1, 0, 0)


def test_blank_rows_are_ignored(factory: UnitOfWorkFactory, ws: str, tmp_path: Path) -> None:
    path = make_workbook(
        tmp_path,
        [row("Acme\nhttps://acme.com", "Jane Doe", "jane@acme.com"), ["", "", "", "", "", "", ""]],
    )
    assert import_legacy_xlsx(factory, ws, path).read == 1


def test_a_workbook_without_the_expected_columns_is_refused(
    factory: UnitOfWorkFactory, ws: str, tmp_path: Path
) -> None:
    path = make_workbook(tmp_path, [["x", "y"]], header=["Company", "Person"])
    with pytest.raises(LegacyWorkbookError, match="Organization URL"):
        import_legacy_xlsx(factory, ws, path)


def test_an_error_partway_undoes_the_whole_import(
    factory: UnitOfWorkFactory, ws: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = make_workbook(
        tmp_path,
        [
            row("Acme\nhttps://acme.com", "Jane Doe", "jane@acme.com"),
            row("Beta\nhttps://beta.io", "Sam Roe", "sam@beta.io"),
        ],
    )
    from outbound.db.repositories import messages as messages_module

    original = messages_module.MessageRepository.create
    calls: list[int] = []

    def flaky(self: messages_module.MessageRepository, **kwargs: object):  # type: ignore[no-untyped-def]
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("disk full")
        return original(self, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(messages_module.MessageRepository, "create", flaky)
    with pytest.raises(RuntimeError):
        import_legacy_xlsx(factory, ws, path)
    with factory(ws) as uow:
        assert counts(uow) == dict.fromkeys(counts(uow), 0)


# ------------------------------------------------------------------ parsing helpers


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        (
            "Open Climate Fix\nhttps://www.openclimatefix.org/contact",
            ("Open Climate Fix", "https://www.openclimatefix.org/contact"),
        ),
        ("https://acme.com", ("", "https://acme.com")),
        ("Acme Ltd", ("Acme Ltd", "")),
        ("Acme\nLtd\nhttps://acme.com", ("Acme Ltd", "https://acme.com")),
        ("", ("", "")),
    ],
)
def test_split_organisation(cell: str, expected: tuple[str, str]) -> None:
    assert split_organisation(cell) == expected


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        (
            "Jack Kelly\n(Co-Founder & Lead Researcher)",
            ("Jack Kelly", "Co-Founder & Lead Researcher"),
        ),
        ("Jack Kelly\nCTO", ("Jack Kelly", "CTO")),
        ("Jack Kelly", ("Jack Kelly", "")),
        ("", ("", "")),
    ],
)
def test_split_person(cell: str, expected: tuple[str, str]) -> None:
    assert split_person(cell) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Jack Kelly", ("Jack", "Kelly")),
        ("Prof. Dr. Hans-Martin Henning", ("Prof.", "Dr. Hans-Martin Henning")),
        ("Cher", ("Cher", None)),
        ("", (None, None)),
    ],
)
def test_split_name(name: str, expected: tuple[str | None, str | None]) -> None:
    assert split_name(name) == expected


def test_import_counts_are_stored_on_the_batch(
    factory: UnitOfWorkFactory, ws: str, tmp_path: Path
) -> None:
    path = make_workbook(
        tmp_path,
        [row("Acme\nhttps://acme.com", "Jane Doe", "jane@acme.com"), row("Nameless", "X", "")],
    )
    result = import_legacy_xlsx(factory, ws, path)
    with factory(ws) as uow:
        stored = uow.session.execute(
            text("SELECT counts FROM import_batches WHERE id = :id"), {"id": result.batch_id}
        ).scalar()
        assert ImportRowStatus.ACCEPTED.value in str(stored) and "rejected" in str(stored)
