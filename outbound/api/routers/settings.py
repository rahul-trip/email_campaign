from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from outbound.api.deps import Services, require, services
from outbound.api.schemas import (
    CampaignIn,
    CampaignOut,
    CampaignPatch,
    PolicyIn,
    PolicyOut,
    SenderProfileIn,
    SuppressionIn,
    SuppressionOut,
    WorkspaceSettingsIn,
)
from outbound.domain.brief import Brief
from outbound.domain.brief import gaps as brief_gaps
from outbound.domain.entities import Campaign
from outbound.domain.permissions import Permission as P
from outbound.domain.ranking import is_role
from outbound.services.settings import profile_template

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _campaign(campaign: Campaign) -> CampaignOut:
    """The campaign with what is weak in it: gaps in its brief, entries in its job titles
    that are not job titles."""
    out = CampaignOut.model_validate(campaign)
    out.brief_gaps = list(brief_gaps(Brief.from_json(campaign.icp_brief)))
    out.title_warnings = [
        f'"{t}" is not a job title, so a search for it finds nobody: use a role such as'
        ' "Head of Operations".'
        for t in campaign.target_titles
        if not is_role(t)
    ]
    return out


@router.get("/sender-profile", dependencies=[Depends(require(P.SETTINGS_READ))])
def sender_profile(svc: Annotated[Services, Depends(services)]) -> dict[str, Any]:
    return svc.settings.sender_profile()


@router.get("/sender-profile/template", dependencies=[Depends(require(P.SETTINGS_READ))])
def sender_profile_template(
    svc: Annotated[Services, Depends(services)], current: bool = False
) -> JSONResponse:
    """A file with every key of the sender profile: empty, or with today's values to edit.
    Upload it back with PUT /sender-profile."""
    body = profile_template(svc.settings.sender_profile() if current else None)
    name = "sender-profile.json" if current else "sender-profile-template.json"
    return JSONResponse(body, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.put("/sender-profile", dependencies=[Depends(require(P.PROFILE_WRITE))])
def update_sender_profile(
    body: SenderProfileIn, svc: Annotated[Services, Depends(services)]
) -> dict[str, Any]:
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    return svc.settings.update_sender_profile(changes)


@router.get("/workspace", dependencies=[Depends(require(P.SETTINGS_READ))])
def workspace_settings(svc: Annotated[Services, Depends(services)]) -> dict[str, Any]:
    return svc.settings.workspace_settings()


@router.put("/workspace", dependencies=[Depends(require(P.SETTINGS_WRITE))])
def update_workspace_settings(
    body: WorkspaceSettingsIn, svc: Annotated[Services, Depends(services)]
) -> dict[str, Any]:
    changes = body.model_dump(exclude_unset=True)
    # Only the budget may be null (it means "no ceiling"); a null anywhere else means "unchanged".
    for name in (
        "safe_to_send_only",
        "few_shot_examples",
        "timezone",
        "country_policy_enabled",
        "footer_enabled",
        "email_min_words",
        "email_max_words",
        "auto_discovery",
    ):
        if changes.get(name, "") is None:
            changes.pop(name)
    return svc.settings.update_workspace_settings(changes)


@router.get(
    "/campaigns", response_model=list[CampaignOut], dependencies=[Depends(require(P.SETTINGS_READ))]
)
def campaigns(svc: Annotated[Services, Depends(services)]) -> list[CampaignOut]:
    return [_campaign(c) for c in svc.settings.campaigns()]


@router.post(
    "/campaigns",
    response_model=CampaignOut,
    status_code=201,
    dependencies=[Depends(require(P.CAMPAIGNS_WRITE))],
)
def create_campaign(body: CampaignIn, svc: Annotated[Services, Depends(services)]) -> CampaignOut:
    fields = body.model_dump(exclude={"name", "target_titles"})
    return _campaign(svc.settings.create_campaign(body.name, body.target_titles, **fields))


@router.patch(
    "/campaigns/{campaign_id}",
    response_model=CampaignOut,
    dependencies=[Depends(require(P.CAMPAIGNS_WRITE))],
)
def update_campaign(
    campaign_id: str, body: CampaignPatch, svc: Annotated[Services, Depends(services)]
) -> CampaignOut:
    changes = body.model_dump(exclude_unset=True)
    return _campaign(svc.settings.update_campaign(campaign_id, changes))


@router.post(
    "/campaigns/{campaign_id}/activate",
    response_model=CampaignOut,
    dependencies=[Depends(require(P.CAMPAIGNS_WRITE))],
)
def activate_campaign(campaign_id: str, svc: Annotated[Services, Depends(services)]) -> CampaignOut:
    """Switch this campaign on; the active one is paused and its leads wait."""
    return _campaign(svc.settings.activate_campaign(campaign_id))


@router.post(
    "/campaigns/{campaign_id}/pause",
    response_model=CampaignOut,
    dependencies=[Depends(require(P.CAMPAIGNS_WRITE))],
)
def pause_campaign(campaign_id: str, svc: Annotated[Services, Depends(services)]) -> CampaignOut:
    return _campaign(svc.settings.pause_campaign(campaign_id))


@router.post(
    "/campaigns/{campaign_id}/brief/regenerate",
    response_model=CampaignOut,
    dependencies=[Depends(require(P.CAMPAIGNS_WRITE))],
)
def regenerate_campaign_brief(
    campaign_id: str, svc: Annotated[Services, Depends(services)]
) -> CampaignOut:
    return _campaign(svc.settings.regenerate_brief(campaign_id))


@router.get(
    "/policies", response_model=list[PolicyOut], dependencies=[Depends(require(P.SETTINGS_READ))]
)
def policies(svc: Annotated[Services, Depends(services)]) -> list[PolicyOut]:
    return [PolicyOut.model_validate(p) for p in svc.settings.policies()]


@router.put(
    "/policies/{country_code}",
    response_model=PolicyOut,
    dependencies=[Depends(require(P.COMPLIANCE_WRITE))],
)
def save_policy(
    country_code: str, body: PolicyIn, svc: Annotated[Services, Depends(services)]
) -> PolicyOut:
    saved = svc.settings.save_policy(
        country_code,
        body.rule,
        requires_corporate_subscriber=body.requires_corporate_subscriber,
        allowed_provenance=body.allowed_provenance,
        footer_template=body.footer_template,
        reviewer=body.reviewed_by,
    )
    return PolicyOut.model_validate(saved)


@router.delete(
    "/policies/{country_code}", status_code=204, dependencies=[Depends(require(P.COMPLIANCE_WRITE))]
)
def delete_policy(country_code: str, svc: Annotated[Services, Depends(services)]) -> None:
    svc.settings.delete_policy(country_code)


@router.get(
    "/suppressions",
    response_model=list[SuppressionOut],
    dependencies=[Depends(require(P.SETTINGS_READ))],
)
def suppressions(svc: Annotated[Services, Depends(services)]) -> list[SuppressionOut]:
    return [SuppressionOut.model_validate(e) for e in svc.settings.suppressions()]


@router.post(
    "/suppressions", status_code=201, dependencies=[Depends(require(P.SUPPRESSIONS_WRITE))]
)
def suppress(body: SuppressionIn, svc: Annotated[Services, Depends(services)]) -> dict[str, bool]:
    return {"added": svc.settings.suppress(body.kind, body.value, body.reason)}


@router.post("/mailboxes/{mailbox_id}/dns-check", dependencies=[Depends(require(P.MAILBOXES_OWN))])
def dns_check(mailbox_id: str, svc: Annotated[Services, Depends(services)]) -> dict[str, object]:
    return svc.settings.dns_check(mailbox_id)
