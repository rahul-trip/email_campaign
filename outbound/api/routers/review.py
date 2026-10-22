from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from outbound.api.deps import Services, services
from outbound.api.schemas import (
    ApproveIn,
    CompanyOut,
    ContactOut,
    EmailOut,
    MessageOut,
    RejectIn,
    ReviewDetailOut,
    ReviewItemOut,
    SkipOut,
)
from outbound.services.review import QueueItem

router = APIRouter(prefix="/api/review", tags=["review"])


def _item(item: QueueItem) -> ReviewItemOut:
    contact = ContactOut.model_validate(
        {**item.contact.__dict__, "emails": [EmailOut.model_validate(item.address)]}
    )
    return ReviewItemOut(
        message=MessageOut.model_validate(item.message),
        company=CompanyOut.model_validate(item.company),
        contact=contact,
        flagged=item.flagged,
        skips=[SkipOut.model_validate(s) for s in item.skips],
    )


@router.get("", response_model=list[ReviewItemOut])
def queue(svc: Annotated[Services, Depends(services)]) -> list[ReviewItemOut]:
    return [_item(i) for i in svc.review.queue()]


@router.get("/{message_id}", response_model=ReviewDetailOut)
def show(message_id: str, svc: Annotated[Services, Depends(services)]) -> ReviewDetailOut:
    detail = svc.review.show(message_id)
    return ReviewDetailOut(item=_item(detail.item), notes=detail.notes)


@router.post("/{message_id}/approve", response_model=MessageOut)
def approve(
    message_id: str, body: ApproveIn, svc: Annotated[Services, Depends(services)]
) -> MessageOut:
    message = svc.review.approve(
        message_id,
        edited_body=body.edited_body,
        expected_version=body.row_version,
        acknowledge_skips=body.acknowledge_skips,
    )
    return MessageOut.model_validate(message)


@router.post("/{message_id}/rewrite", response_model=CompanyOut)
def rewrite(message_id: str, svc: Annotated[Services, Depends(services)]) -> CompanyOut:
    """Throw this email away and have the next run write a new one to the same person.

    The email is cancelled and the lead goes back to the email step, which reuses the address it
    already has at no cost; the copy step then writes it again under the current rules and news.
    """
    item = svc.review.show(message_id).item
    return CompanyOut.model_validate(svc.leads.change_recipient(item.company.id, item.contact.id))


@router.post("/{message_id}/reject", response_model=MessageOut)
def reject(
    message_id: str, body: RejectIn, svc: Annotated[Services, Depends(services)]
) -> MessageOut:
    return MessageOut.model_validate(svc.review.reject(message_id, body.reason))
