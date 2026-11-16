"""What the workspace still has to set up (Phase 6c)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from outbound.api.deps import Services, require, services
from outbound.api.schemas import (
    CampaignDraftOut,
    ProfileDraftIn,
    ProfileDraftOut,
    SetupItemOut,
    SetupOut,
)
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


@router.post(
    "/profile-draft",
    response_model=ProfileDraftOut,
    dependencies=[Depends(require(P.PROFILE_WRITE))],
)
def profile_draft(
    body: ProfileDraftIn, svc: Annotated[Services, Depends(services)]
) -> ProfileDraftOut:
    """Read the company's own website and suggest profile fields. Saves nothing."""
    found = svc.drafts.profile(body.website)
    return ProfileDraftOut(
        drafted=found.drafted,
        reason=found.reason,
        fields=found.fields,
        pages=list(found.pages),
    )


@router.post(
    "/campaign-draft",
    response_model=CampaignDraftOut,
    dependencies=[Depends(require(P.CAMPAIGNS_WRITE))],
)
def campaign_draft(svc: Annotated[Services, Depends(services)]) -> CampaignDraftOut:
    """Suggest job titles, an ideal customer and questions from the saved profile. Saves nothing."""
    found = svc.drafts.campaign()
    return CampaignDraftOut(
        drafted=found.drafted,
        reason=found.reason,
        target_titles=list(found.target_titles),
        icp_description=found.icp_description,
        research_questions=list(found.research_questions),
    )
