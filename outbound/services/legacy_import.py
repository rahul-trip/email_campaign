"""One-time import of the legacy campaign workbook into the lead store.

Every sheet row becomes an ``import_rows`` record holding the whole row exactly as it was. A
row whose company is new also becomes a company, a contact, an address, a note and a drafted
message, so those leads are de-duplicated and are never drafted again. Running it twice
changes nothing: the second run finds every company already there and marks the rows merged.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import openpyxl

from outbound.db.uow import UnitOfWork, UnitOfWorkFactory
from outbound.domain.actors import OPERATOR
from outbound.domain.domains import registrable_domain
from outbound.domain.enums import (
    CompanySource,
    CompanyStatus,
    ContactSource,
    ContactStatus,
    EntityType,
    ImportAnchor,
    ImportRowStatus,
    ImportSource,
    MessageState,
    NoteSource,
    Provenance,
)

COLUMNS = (
    "Organization URL",
    "Specific Person to Contact",
    "POC Details & Eccentricities",
    "Direct Business Email",
    "Tailored Pitch Email",
    "Follow-up Text",
    "Points of Commonality",
)


class LegacyWorkbookError(ValueError):
    """The workbook is not the campaign matrix this importer understands."""


@dataclass(frozen=True)
class LegacyRow:
    number: int  # the spreadsheet row, header being 1
    values: dict[str, str]


@dataclass(frozen=True)
class LegacyImportResult:
    batch_id: str
    read: int
    imported: int
    merged: int
    rejected: int


def read_rows(path: Path) -> Iterator[LegacyRow]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook.worksheets[0] if workbook.worksheets else None
        if sheet is None:
            raise LegacyWorkbookError(f"{path.name} has no worksheet")
        rows = sheet.iter_rows(values_only=True)
        header = [str(cell).strip() if cell is not None else "" for cell in next(rows, ())]
        missing = [name for name in COLUMNS if name not in header]
        if missing:
            raise LegacyWorkbookError(f"{path.name} is missing column(s): {missing}")
        index = {name: header.index(name) for name in COLUMNS}
        for number, cells in enumerate(rows, start=2):
            values = {
                name: (str(cells[i]).strip() if i < len(cells) and cells[i] is not None else "")
                for name, i in index.items()
            }
            if any(values.values()):
                yield LegacyRow(number, values)
    finally:
        workbook.close()


def split_organisation(cell: str) -> tuple[str, str]:
    """``"Name\\nhttps://site"`` becomes (name, url); either part may be empty."""
    name_parts: list[str] = []
    url = ""
    for line in (part.strip() for part in cell.splitlines()):
        if line.lower().startswith("http") and not url:
            url = line
        elif line:
            name_parts.append(line)
    return " ".join(name_parts), url


def split_person(cell: str) -> tuple[str, str]:
    """``"Jack Kelly\\n(Co-Founder)"`` becomes (name, title)."""
    lines = [line.strip() for line in cell.splitlines() if line.strip()]
    if not lines:
        return "", ""
    title = " ".join(lines[1:])
    match = re.fullmatch(r"\((.*)\)", title)
    return lines[0], (match.group(1).strip() if match else title)


def split_name(full_name: str) -> tuple[str | None, str | None]:
    parts = full_name.split()
    if not parts:
        return None, None
    return parts[0], " ".join(parts[1:]) or None


def import_legacy_xlsx(
    factory: UnitOfWorkFactory, workspace_id: str, path: Path, *, actor: str = OPERATOR
) -> LegacyImportResult:
    """Import every row in one transaction: all of it, or none of it."""
    rows = list(read_rows(path))
    imported = merged = rejected = 0
    with factory(workspace_id) as uow:
        batch_id = uow.imports.create_batch(ImportSource.LEGACY_XLSX, actor, filename=path.name)
        for row in rows:
            outcome = _import_row(uow, batch_id, row, path.name, actor)
            if outcome is ImportRowStatus.ACCEPTED:
                imported += 1
            elif outcome is ImportRowStatus.MERGED:
                merged += 1
            else:
                rejected += 1
        uow.imports.finish_batch(batch_id)
        uow.commit()
    return LegacyImportResult(batch_id, len(rows), imported, merged, rejected)


def _import_row(
    uow: UnitOfWork, batch_id: str, row: LegacyRow, filename: str, actor: str
) -> ImportRowStatus:
    organisation, url = split_organisation(row.values["Organization URL"])
    email = row.values["Direct Business Email"].lower()
    domain = registrable_domain(url) or (registrable_domain(email) if email else None)
    anchor = ImportAnchor.DOMAIN if registrable_domain(url) else ImportAnchor.EMAIL

    def record(
        status: ImportRowStatus, *, reason: str | None = None, company_id: str | None = None
    ) -> ImportRowStatus:
        uow.imports.add_row(
            batch_id,
            dict(row.values),  # the whole row, so nothing in the sheet is lost
            anchor if domain else ImportAnchor.COMPANY_NAME,
            status,
            row_number=row.number,
            resolved_domain=domain,
            reason=reason,
            company_id=company_id,
        )
        return status

    if domain is None:
        return record(ImportRowStatus.REJECTED, reason="no usable website or email domain")

    existing = uow.companies.by_domain(domain)
    if existing is not None:
        return record(ImportRowStatus.MERGED, company_id=existing.id)

    company = uow.companies.create(
        domain=domain,
        name=organisation or None,
        source=CompanySource.IMPORT,
        status=CompanyStatus.COMPLETED,  # these leads were already drafted
        actor=actor,
    )
    uow.events.append(
        EntityType.COMPANY,
        company.id,
        "legacy_imported",
        actor,
        {"file": filename, "sheet_row": row.number},
    )

    name, title = split_person(row.values["Specific Person to Contact"])
    contact_id: str | None = None
    if name:
        first, last = split_name(name)
        contact = uow.contacts.add(
            company.id,
            rank=1,
            source=ContactSource.OPERATOR,
            full_name=name,
            first_name=first,
            last_name=last,
            title=title or None,
            status=ContactStatus.ACTIVE,
            actor=actor,
        )
        contact_id = contact.id

    details = row.values["POC Details & Eccentricities"]
    if details:
        uow.notes.add(company.id, details, NoteSource.IMPORT, author=actor, contact_id=contact_id)

    reason: str | None = None
    pitch = row.values["Tailored Pitch Email"]
    if contact_id and email and pitch:
        if uow.emails.by_address(email) is not None:
            reason = "address already belongs to another contact; no message created"
        else:
            address = uow.emails.add(
                contact_id,
                email,
                Provenance.OPERATOR_GIVEN,
                is_primary=True,
                actor=actor,
            )
            uow.messages.create(
                company_id=company.id,
                contact_id=contact_id,
                contact_email_id=address.id,
                step=0,
                subject=organisation or domain,  # what the legacy mailer used as the subject
                generated_body=pitch,
                state=MessageState.DRAFTED,
                actor=actor,
            )
    elif pitch:
        reason = "no contact or address; the pitch is kept only in the import row"
    return record(ImportRowStatus.ACCEPTED, reason=reason, company_id=company.id)
