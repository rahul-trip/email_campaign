from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from outbound.api.deps import Services, services
from outbound.api.schemas import (
    CompanyOut,
    CompanyPage,
    ConsentIn,
    ConsentOut,
    ContactOut,
    EmailOut,
    JourneyOut,
    LeadOut,
    MessageOut,
    NoteOut,
    ReleaseIn,
    TimelineOut,
    WaterfallOut,
)
from outbound.domain.enums import CompanyStatus, HoldReason
from outbound.services.leads import LeadDetail

router = APIRouter(prefix="/api", tags=["leads"])


def _lead(detail: LeadDetail) -> LeadOut:
    return LeadOut(
        company=CompanyOut.model_validate(detail.company),
        contacts=[
            ContactOut.model_validate(
                {**c.contact.__dict__, "emails": [EmailOut.model_validate(e) for e in c.emails]}
            )
            for c in detail.contacts
        ],
        messages=[MessageOut.model_validate(m) for m in detail.messages],
        notes=[NoteOut.model_validate(n) for n in detail.notes],
    )


@router.get("/companies", response_model=CompanyPage)
def companies(
    svc: Annotated[Services, Depends(services)],
    status: CompanyStatus | None = None,
    hold_reason: HoldReason | None = None,
    campaign_id: str | None = None,
    q: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CompanyPage:
    items, total = svc.leads.search(
        status=status,
        hold_reason=hold_reason,
        campaign_id=campaign_id,
        text=q,
        limit=limit,
        offset=offset,
    )
    return CompanyPage(items=[CompanyOut.model_validate(c) for c in items], total=total)


@router.get("/companies/{company_id}", response_model=LeadOut)
def company(company_id: str, svc: Annotated[Services, Depends(services)]) -> LeadOut:
    return _lead(svc.leads.detail(company_id))


@router.get("/companies/{company_id}/journey", response_model=JourneyOut)
def journey(company_id: str, svc: Annotated[Services, Depends(services)]) -> JourneyOut:
    return JourneyOut.model_validate(svc.leads.journey(company_id))


@router.get("/companies/{company_id}/timeline", response_model=list[TimelineOut])
def timeline(company_id: str, svc: Annotated[Services, Depends(services)]) -> list[TimelineOut]:
    return [TimelineOut.model_validate(e) for e in svc.leads.timeline(company_id)]


@router.get("/companies/{company_id}/waterfall", response_model=list[WaterfallOut])
def waterfall(company_id: str, svc: Annotated[Services, Depends(services)]) -> list[WaterfallOut]:
    return [WaterfallOut.model_validate(s) for s in svc.leads.waterfall(company_id)]


@router.post("/companies/{company_id}/retry", response_model=CompanyOut)
def retry(company_id: str, svc: Annotated[Services, Depends(services)]) -> CompanyOut:
    return CompanyOut.model_validate(svc.leads.retry(company_id))


@router.post("/companies/{company_id}/release-hold", response_model=CompanyOut)
def release_hold(
    company_id: str, body: ReleaseIn, svc: Annotated[Services, Depends(services)]
) -> CompanyOut:
    return CompanyOut.model_validate(svc.leads.release_hold(company_id, resume_to=body.resume_to))


@router.post("/companies/{company_id}/requalify", response_model=CompanyOut)
def requalify(company_id: str, svc: Annotated[Services, Depends(services)]) -> CompanyOut:
    return CompanyOut.model_validate(svc.leads.requalify(company_id))


@router.post("/contacts/{contact_id}/consents", response_model=ConsentOut, status_code=201)
def consent(
    contact_id: str, body: ConsentIn, svc: Annotated[Services, Depends(services)]
) -> ConsentOut:
    return ConsentOut.model_validate(
        svc.leads.record_consent(contact_id, body.basis, body.evidence)
    )
