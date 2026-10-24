"""What the workspace still has to set up (Phase 6c)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from outbound.api.deps import Services, require, services
from outbound.api.schemas import SetupItemOut, SetupOut
from outbound.domain.permissions import Permission as P

router = APIRouter(prefix="/api/setup", tags=["setup"])


@router.get("", response_model=SetupOut, dependencies=[Depends(require(P.SETTINGS_READ))])
def setup(svc: Annotated[Services, Depends(services)]) -> SetupOut:
    report = svc.setup.report()
    return SetupOut(
        items=[SetupItemOut.model_validate(i, from_attributes=True) for i in report.items],
        done=report.done,
        next=SetupItemOut.model_validate(report.next, from_attributes=True)
        if report.next
        else None,
    )
