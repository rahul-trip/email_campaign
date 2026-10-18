from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile

from outbound.api.deps import Services, services
from outbound.api.schemas import (
    CompanyOut,
    CompanyPatch,
    ConfirmIn,
    IntakeOut,
    RowOut,
    TargetIn,
    WaitingRowOut,
)
from outbound.domain.enums import ImportSource
from outbound.services.intake import IntakeReport, load_rows

router = APIRouter(prefix="/api", tags=["targets"])
MAX_UPLOAD_BYTES = 2_000_000


def _out(report: IntakeReport) -> IntakeOut:
    return IntakeOut(
        batch_id=report.batch_id,
        validate_only=report.validate_only,
        rows=[RowOut.model_validate(r) for r in report.rows],
    )


@router.post("/targets", response_model=IntakeOut)
def add_target(body: TargetIn, svc: Annotated[Services, Depends(services)]) -> IntakeOut:
    row = body.model_dump(exclude={"campaign_id", "validate_only"}, exclude_none=True)
    report = svc.intake.run(
        [row],
        source=ImportSource.UI,
        campaign_id=body.campaign_id,
        validate_only=body.validate_only,
    )
    return _out(report)


@router.post("/targets/upload", response_model=IntakeOut)
async def upload_targets(
    svc: Annotated[Services, Depends(services)],
    file: Annotated[UploadFile, File()],
    campaign_id: Annotated[str | None, Form()] = None,
    preview: Annotated[bool, Form()] = True,
) -> IntakeOut:
    """Read a CSV or XLSX. ``preview`` (the default) checks it and saves nothing."""
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("the file is larger than 2 MB")
    suffix = Path(file.filename or "targets.csv").suffix.lower()
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / f"upload{suffix}"
        path.write_bytes(data)
        rows = load_rows(path)
    source = ImportSource.XLSX if suffix.startswith(".xls") else ImportSource.CSV
    report = svc.intake.run(
        rows,
        source=source,
        campaign_id=campaign_id,
        filename=file.filename,
        validate_only=preview,
    )
    return _out(report)


@router.get("/targets/waiting", response_model=list[WaitingRowOut])
def waiting(svc: Annotated[Services, Depends(services)]) -> list[WaitingRowOut]:
    return [WaitingRowOut.model_validate(r) for r in svc.intake.needing_confirmation()]


@router.post("/targets/{row_id}/confirm", response_model=RowOut)
def confirm(row_id: str, body: ConfirmIn, svc: Annotated[Services, Depends(services)]) -> RowOut:
    return RowOut.model_validate(svc.intake.confirm(row_id, body.domain))


@router.patch("/companies/{company_id}", response_model=CompanyOut)
def edit_company(
    company_id: str, body: CompanyPatch, svc: Annotated[Services, Depends(services)]
) -> CompanyOut:
    changes = body.model_dump(exclude={"row_version"}, exclude_none=True)
    updated = svc.leads.update(company_id, changes, expected_version=body.row_version)
    return CompanyOut.model_validate(updated)
