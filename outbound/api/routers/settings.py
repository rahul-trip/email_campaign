from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from outbound.api.deps import Services, require, services
from outbound.api.schemas import (
    CampaignIn,
    CampaignOut,
    CampaignPatch,
    MailboxIn,
    MailboxOut,
    PolicyIn,
    PolicyOut,
    SenderProfileIn,
    SuppressionIn,
    SuppressionOut,
    WorkspaceSettingsIn,
)
from outbound.domain.permissions import Permission as P

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/sender-profile", dependencies=[Depends(require(P.SETTINGS_READ))])
def sender_profile(svc: Annotated[Services, Depends(services)]) -> dict[str, Any]:
    return svc.settings.sender_profile()


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
    ):
        if changes.get(name, "") is None:
            changes.pop(name)
    return svc.settings.update_workspace_settings(changes)


@router.get(
    "/campaigns", response_model=list[CampaignOut], dependencies=[Depends(require(P.SETTINGS_READ))]
)
def campaigns(svc: Annotated[Services, Depends(services)]) -> list[CampaignOut]:
    return [CampaignOut.model_validate(c) for c in svc.settings.campaigns()]


@router.post(
    "/campaigns",
    response_model=CampaignOut,
    status_code=201,
    dependencies=[Depends(require(P.CAMPAIGNS_WRITE))],
)
def create_campaign(body: CampaignIn, svc: Annotated[Services, Depends(services)]) -> CampaignOut:
    fields = body.model_dump(exclude={"name", "target_titles"})
    return CampaignOut.model_validate(
        svc.settings.create_campaign(body.name, body.target_titles, **fields)
    )


@router.patch(
    "/campaigns/{campaign_id}",
    response_model=CampaignOut,
    dependencies=[Depends(require(P.CAMPAIGNS_WRITE))],
)
def update_campaign(
    campaign_id: str, body: CampaignPatch, svc: Annotated[Services, Depends(services)]
) -> CampaignOut:
    changes = body.model_dump(exclude_unset=True)
    return CampaignOut.model_validate(svc.settings.update_campaign(campaign_id, changes))


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


@router.get(
    "/mailboxes", response_model=list[MailboxOut], dependencies=[Depends(require(P.SETTINGS_READ))]
)
def mailboxes(svc: Annotated[Services, Depends(services)]) -> list[MailboxOut]:
    return [MailboxOut.model_validate(m) for m in svc.settings.mailboxes()]


@router.post(
    "/mailboxes",
    response_model=MailboxOut,
    status_code=201,
    dependencies=[Depends(require(P.MAILBOXES_MANAGE))],
)
def add_mailbox(body: MailboxIn, svc: Annotated[Services, Depends(services)]) -> MailboxOut:
    box = svc.settings.add_mailbox(body.address, body.credentials_ref, daily_cap=body.daily_cap)
    return MailboxOut.model_validate(box)


@router.post("/mailboxes/{mailbox_id}/dns-check", dependencies=[Depends(require(P.MAILBOXES_OWN))])
def dns_check(mailbox_id: str, svc: Annotated[Services, Depends(services)]) -> dict[str, object]:
    return svc.settings.dns_check(mailbox_id)
