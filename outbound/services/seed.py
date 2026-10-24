"""Create the default workspace (empty, for a developer or the first install) and its starting
rows. Safe to run again."""

from __future__ import annotations

from dataclasses import dataclass

from outbound.db.platform import PlatformUnitOfWorkFactory
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.policy_seeds import DEFAULT_COUNTRY_POLICIES
from outbound.services import defaults
from outbound.services.workspaces import add_starting_rows, create_workspace


@dataclass(frozen=True)
class SeedResult:
    workspace_id: str
    workspace_created: bool
    campaign_created: bool
    policies_created: int


def seed_defaults(
    factory: UnitOfWorkFactory,
    platform: PlatformUnitOfWorkFactory,
    workspace_name: str = defaults.DEFAULT_WORKSPACE_NAME,
) -> SeedResult:
    with platform() as directory:
        existing = directory.workspaces.by_name(workspace_name)
    if existing is None:
        created = create_workspace(factory, platform, workspace_name)
        return SeedResult(created.id, True, True, len(DEFAULT_COUNTRY_POLICIES))
    policies_created, campaign_created = add_starting_rows(factory, existing.id)
    return SeedResult(existing.id, False, campaign_created, policies_created)
