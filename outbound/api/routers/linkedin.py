"""LinkedIn messages written for the operator to paste by hand; nothing is sent from here."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from outbound.api.deps import Services, require, services
from outbound.api.schemas import (
    LinkedInDraftOut,
    LinkedInDraftPage,
    LinkedInDraftRowOut,
    LinkedInEditIn,
    LinkedInSentOut,
)
from outbound.domain.enums import LinkedInState
from outbound.domain.permissions import Permission as P

router = APIRouter(prefix="/api", tags=["linkedin"])
Svc = Annotated[Services, Depends(services)]
READ = [Depends(require(P.LEADS_READ))]
WRITE = [Depends(require(P.LEADS_WRITE))]


def _out(message: object) -> LinkedInDraftOut:
    return LinkedInDraftOut.model_validate(message, from_attributes=True)


@router.get("/linkedin", response_model=LinkedInDraftPage, dependencies=READ)
def drafts(
    svc: Svc,
    state: LinkedInState = LinkedInState.DRAFTED,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LinkedInDraftPage:
    """Every message in one state, newest first, with who it is for."""
    rows, total = svc.linkedin.page(state, limit=limit, offset=offset)
    return LinkedInDraftPage(
        items=[
            LinkedInDraftRowOut(
                item=_out(r.message),
                company_name=r.company_name,
                domain=r.domain,
                person=r.person,
                title=r.title,
                profile=r.profile,
            )
            for r in rows
        ],
        total=total,
    )


@router.get(
    "/companies/{company_id}/linkedin", response_model=list[LinkedInDraftOut], dependencies=READ
)
def company_drafts(company_id: str, svc: Svc) -> list[LinkedInDraftOut]:
    return [_out(m) for m in svc.linkedin.for_company(company_id)]


@router.post("/contacts/{contact_id}/linkedin", response_model=LinkedInDraftOut, dependencies=WRITE)
def write_draft(contact_id: str, svc: Svc) -> LinkedInDraftOut:
    """Write (or rewrite) the connection note and message for one person who works here."""
    return _out(svc.linkedin.write(contact_id))


@router.patch("/linkedin/{linkedin_id}", response_model=LinkedInDraftOut, dependencies=WRITE)
def edit_draft(linkedin_id: str, body: LinkedInEditIn, svc: Svc) -> LinkedInDraftOut:
    return _out(svc.linkedin.edit(linkedin_id, note=body.note, message=body.message))


@router.post("/linkedin/{linkedin_id}/sent", response_model=LinkedInSentOut, dependencies=WRITE)
def mark_sent(linkedin_id: str, svc: Svc) -> LinkedInSentOut:
    """Say you sent it on LinkedIn. The lead's email then waits until you release it."""
    result = svc.linkedin.mark_sent(linkedin_id)
    return LinkedInSentOut(item=_out(result.message), email_held=result.email_held)


@router.post("/linkedin/{linkedin_id}/skip", response_model=LinkedInDraftOut, dependencies=WRITE)
def skip_draft(linkedin_id: str, svc: Svc) -> LinkedInDraftOut:
    return _out(svc.linkedin.skip(linkedin_id))


@router.post("/linkedin/{linkedin_id}/restore", response_model=LinkedInDraftOut, dependencies=WRITE)
def restore_draft(linkedin_id: str, svc: Svc) -> LinkedInDraftOut:
    return _out(svc.linkedin.restore(linkedin_id))
