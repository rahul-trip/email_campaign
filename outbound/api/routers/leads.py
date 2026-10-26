from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from outbound.api.deps import Services, require, services
from outbound.api.schemas import (
    CompanyOut,
    CompanyPage,
    ConsentIn,
    ConsentOut,
    ContactOut,
    DirectoryBadgeOut,
    DirectoryReportIn,
    DirectorySkipIn,
    EmailOut,
    JourneyOut,
    LeadOut,
    MessageOut,
    NoteOut,
    PersonIn,
    PersonPatch,
    PolicySkipIn,
    RecipientIn,
    ReleaseIn,
    SkipCheckIn,
    TimelineOut,
    WaterfallOut,
)
from outbound.domain.enums import CompanyStatus, HoldReason
from outbound.domain.permissions import Permission as P
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
        held_at=detail.held_at.value if detail.held_at else None,
    )


@router.get("/companies", response_model=CompanyPage, dependencies=[Depends(require(P.LEADS_READ))])
def companies(
    svc: Annotated[Services, Depends(services)],
    status: CompanyStatus | None = None,
    hold_reason: HoldReason | None = None,
    campaign_id: str | None = None,
    q: str | None = None,
    waiting_for_credits: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CompanyPage:
    items, total = svc.leads.search(
        status=status,
        hold_reason=hold_reason,
        campaign_id=campaign_id,
        text=q,
        waiting_for_credits=waiting_for_credits,
        limit=limit,
        offset=offset,
    )
    return CompanyPage(items=[CompanyOut.model_validate(c) for c in items], total=total)


@router.get(
    "/companies/{company_id}", response_model=LeadOut, dependencies=[Depends(require(P.LEADS_READ))]
)
def company(company_id: str, svc: Annotated[Services, Depends(services)]) -> LeadOut:
    return _lead(svc.leads.detail(company_id))


@router.get(
    "/companies/{company_id}/journey",
    response_model=JourneyOut,
    dependencies=[Depends(require(P.LEADS_READ))],
)
def journey(company_id: str, svc: Annotated[Services, Depends(services)]) -> JourneyOut:
    return JourneyOut.model_validate(svc.leads.journey(company_id))


@router.get(
    "/companies/{company_id}/timeline",
    response_model=list[TimelineOut],
    dependencies=[Depends(require(P.LEADS_READ))],
)
def timeline(company_id: str, svc: Annotated[Services, Depends(services)]) -> list[TimelineOut]:
    return [TimelineOut.model_validate(e) for e in svc.leads.timeline(company_id)]


@router.get(
    "/companies/{company_id}/waterfall",
    response_model=list[WaterfallOut],
    dependencies=[Depends(require(P.LEADS_READ))],
)
def waterfall(company_id: str, svc: Annotated[Services, Depends(services)]) -> list[WaterfallOut]:
    return [WaterfallOut.model_validate(s) for s in svc.leads.waterfall(company_id)]


@router.post(
    "/companies/{company_id}/retry",
    response_model=CompanyOut,
    dependencies=[Depends(require(P.LEADS_WRITE))],
)
def retry(company_id: str, svc: Annotated[Services, Depends(services)]) -> CompanyOut:
    return CompanyOut.model_validate(svc.leads.retry(company_id))


@router.post(
    "/companies/{company_id}/release-hold",
    response_model=CompanyOut,
    dependencies=[Depends(require(P.LEADS_WRITE))],
)
def release_hold(
    company_id: str, body: ReleaseIn, svc: Annotated[Services, Depends(services)]
) -> CompanyOut:
    return CompanyOut.model_validate(svc.leads.release_hold(company_id, resume_to=body.resume_to))


@router.post(
    "/companies/{company_id}/research-again",
    response_model=CompanyOut,
    dependencies=[Depends(require(P.LEADS_WRITE))],
)
def research_again(company_id: str, svc: Annotated[Services, Depends(services)]) -> CompanyOut:
    return CompanyOut.model_validate(svc.leads.research_again(company_id))


@router.post(
    "/companies/{company_id}/requalify",
    response_model=CompanyOut,
    dependencies=[Depends(require(P.LEADS_WRITE))],
)
def requalify(company_id: str, svc: Annotated[Services, Depends(services)]) -> CompanyOut:
    return CompanyOut.model_validate(svc.leads.requalify(company_id))


@router.post(
    "/companies/{company_id}/policy-skip",
    response_model=CompanyOut,
    dependencies=[Depends(require(P.COMPLIANCE_WRITE))],
)
def skip_policy(
    company_id: str, body: PolicySkipIn, svc: Annotated[Services, Depends(services)]
) -> CompanyOut:
    return CompanyOut.model_validate(
        svc.leads.skip_policy(company_id, body.from_stage, body.reason)
    )


@router.delete(
    "/companies/{company_id}/policy-skip",
    response_model=CompanyOut,
    dependencies=[Depends(require(P.COMPLIANCE_WRITE))],
)
def revoke_policy_skip(company_id: str, svc: Annotated[Services, Depends(services)]) -> CompanyOut:
    return CompanyOut.model_validate(svc.leads.revoke_policy_skip(company_id))


@router.post("/companies/release-policy-holds", dependencies=[Depends(require(P.COMPLIANCE_WRITE))])
def release_policy_holds(svc: Annotated[Services, Depends(services)]) -> dict[str, int]:
    return {"released": svc.leads.release_policy_holds()}


@router.post(
    "/companies/{company_id}/change-recipient",
    response_model=CompanyOut,
    dependencies=[Depends(require(P.LEADS_WRITE))],
)
def change_recipient(
    company_id: str, body: RecipientIn, svc: Annotated[Services, Depends(services)]
) -> CompanyOut:
    return CompanyOut.model_validate(svc.leads.change_recipient(company_id, body.contact_id))


@router.post(
    "/companies/{company_id}/people",
    response_model=ContactOut,
    status_code=201,
    dependencies=[Depends(require(P.LEADS_WRITE))],
)
def add_person(
    company_id: str, body: PersonIn, svc: Annotated[Services, Depends(services)]
) -> ContactOut:
    added = svc.leads.add_person(
        company_id,
        full_name=body.full_name,
        title=body.title,
        email=body.email,
        consent_basis=body.consent_basis,
        consent_evidence=body.consent_evidence,
    )
    return ContactOut.model_validate(
        {**added.contact.__dict__, "emails": [EmailOut.model_validate(e) for e in added.emails]}
    )


@router.patch(
    "/contacts/{contact_id}",
    response_model=ContactOut,
    dependencies=[Depends(require(P.LEADS_WRITE))],
)
def edit_person(
    contact_id: str, body: PersonPatch, svc: Annotated[Services, Depends(services)]
) -> ContactOut:
    updated = svc.leads.update_person(
        contact_id, full_name=body.full_name, title=body.title, email=body.email
    )
    return ContactOut.model_validate(
        {**updated.contact.__dict__, "emails": [EmailOut.model_validate(e) for e in updated.emails]}
    )


@router.post(
    "/contacts/{contact_id}/consents",
    response_model=ConsentOut,
    status_code=201,
    dependencies=[Depends(require(P.LEADS_WRITE))],
)
def consent(
    contact_id: str, body: ConsentIn, svc: Annotated[Services, Depends(services)]
) -> ConsentOut:
    return ConsentOut.model_validate(
        svc.leads.record_consent(contact_id, body.basis, body.evidence)
    )


@router.delete(
    "/contacts/{contact_id}", status_code=204, dependencies=[Depends(require(P.LEADS_WRITE))]
)
def remove_person(contact_id: str, svc: Annotated[Services, Depends(services)]) -> None:
    svc.leads.remove_person(contact_id)


@router.post(
    "/contacts/{contact_id}/confirm",
    response_model=ContactOut,
    dependencies=[Depends(require(P.LEADS_WRITE))],
)
def confirm_person(contact_id: str, svc: Annotated[Services, Depends(services)]) -> ContactOut:
    confirmed = svc.leads.confirm_person(contact_id)
    return ContactOut.model_validate(
        {
            **confirmed.contact.__dict__,
            "emails": [EmailOut.model_validate(e) for e in confirmed.emails],
        }
    )


@router.post(
    "/contact-emails/{email_id}/skip-verification",
    response_model=ContactOut,
    dependencies=[Depends(require(P.LEADS_WRITE))],
)
def skip_email_verification(
    email_id: str, body: SkipCheckIn, svc: Annotated[Services, Depends(services)]
) -> ContactOut:
    person = svc.leads.skip_email_verification(email_id, body.reason)
    return ContactOut.model_validate(
        {**person.contact.__dict__, "emails": [EmailOut.model_validate(e) for e in person.emails]}
    )


@router.delete(
    "/contact-emails/{email_id}/skip-verification",
    response_model=ContactOut,
    dependencies=[Depends(require(P.LEADS_WRITE))],
)
def restore_email_verification(
    email_id: str, svc: Annotated[Services, Depends(services)]
) -> ContactOut:
    person = svc.leads.restore_email_verification(email_id)
    return ContactOut.model_validate(
        {**person.contact.__dict__, "emails": [EmailOut.model_validate(e) for e in person.emails]}
    )


@router.get(
    "/companies/{company_id}/directory",
    response_model=DirectoryBadgeOut,
    dependencies=[Depends(require(P.LEADS_READ))],
)
def directory_badge(
    company_id: str, svc: Annotated[Services, Depends(services)]
) -> DirectoryBadgeOut:
    badge = svc.directory.badge(company_id)
    return DirectoryBadgeOut(
        in_directory=badge.in_directory,
        verified_month=badge.verified_month,
        can_skip=badge.can_skip,
        skipping=badge.skipping,
    )


@router.post(
    "/companies/{company_id}/directory/report",
    status_code=204,
    dependencies=[Depends(require(P.DIRECTORY_REPORT))],
)
def directory_report(
    company_id: str, body: DirectoryReportIn, svc: Annotated[Services, Depends(services)]
) -> None:
    svc.directory.report(company_id, body.field, body.reason)


@router.put(
    "/companies/{company_id}/directory/skip",
    response_model=DirectoryBadgeOut,
    dependencies=[Depends(require(P.DIRECTORY_SKIP))],
)
def directory_skip(
    company_id: str, body: DirectorySkipIn, svc: Annotated[Services, Depends(services)]
) -> DirectoryBadgeOut:
    svc.directory.skip(company_id, body.skip)
    return directory_badge(company_id, svc)
