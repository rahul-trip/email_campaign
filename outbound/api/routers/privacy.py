from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from outbound.api.deps import Services, services
from outbound.api.schemas import ForgetIn, PrivacyOut
from outbound.services.privacy import PrivacyResult

router = APIRouter(prefix="/api", tags=["privacy"])


def _out(result: PrivacyResult) -> PrivacyOut:
    return PrivacyOut(
        found=result.found,
        messages_cancelled=result.messages_cancelled,
        drafts_deleted=result.drafts_deleted,
        drafts_left=list(result.drafts_left),
    )


@router.post("/privacy/forget", response_model=PrivacyOut)
def forget(body: ForgetIn, svc: Annotated[Services, Depends(services)]) -> PrivacyOut:
    """Erase a person: suppress the address for good and remove what identifies them."""
    return _out(svc.privacy.forget(body.email))


@router.post("/contacts/{contact_id}/suppress", response_model=PrivacyOut)
def suppress_contact(contact_id: str, svc: Annotated[Services, Depends(services)]) -> PrivacyOut:
    """Never contact this person again; their unsent emails are cancelled."""
    return _out(svc.privacy.suppress_contact(contact_id))


@router.post("/companies/{company_id}/suppress", response_model=PrivacyOut)
def suppress_company(company_id: str, svc: Annotated[Services, Depends(services)]) -> PrivacyOut:
    """Never contact anyone at this company's domain again."""
    return _out(svc.privacy.suppress_company(company_id))
