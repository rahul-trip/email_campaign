"""The platform's own console (Phase 6b starts it; 6d fills it in): staff only."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from outbound.api.deps import identity, require_platform
from outbound.api.errors import ApiError
from outbound.api.schemas import CustomerIn, CustomerOut
from outbound.domain.permissions import Permission as P
from outbound.services.identity import CurrentUser, IdentityError, IdentityService

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/customers", response_model=CustomerOut, status_code=201)
def create_customer(
    body: CustomerIn,
    staff: Annotated[CurrentUser, Depends(require_platform(P.ADMIN_WRITE))],
    ids: Annotated[IdentityService, Depends(identity)],
) -> CustomerOut:
    """Create a customer's workspace and invite its first admin."""
    try:
        workspace, invitation = ids.create_customer(
            body.name, body.admin_email, by=staff.user.id, website=body.website
        )
    except IdentityError as error:
        raise ApiError(error.status, error.code, error.detail) from None
    return CustomerOut(workspace_id=workspace.id, slug=workspace.slug, invited=invitation.email)
