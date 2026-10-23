"""Create the default workspace, campaign and country policies. Safe to run again."""

from __future__ import annotations

from dataclasses import dataclass

from outbound.db.platform import PlatformUnitOfWorkFactory
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.policy_seeds import DEFAULT_COUNTRY_POLICIES
from outbound.services import defaults


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
        workspace = directory.workspaces.by_name(workspace_name)
        created = workspace is None
        if workspace is None:
            workspace = directory.workspaces.create(
                workspace_name,
                defaults.default_sender_profile(),
                defaults.default_workspace_settings(),
            )
        directory.commit()

    with factory(workspace.id) as uow:
        policies_created = sum(
            uow.policies.add_if_missing(policy) for policy in DEFAULT_COUNTRY_POLICIES
        )
        campaign_created = uow.campaigns.by_name(defaults.DEFAULT_CAMPAIGN_NAME) is None
        if campaign_created:
            uow.campaigns.create(
                defaults.DEFAULT_CAMPAIGN_NAME,
                list(defaults.DEFAULT_TARGET_TITLES),
                icp_description=defaults.DEFAULT_ICP,
            )
        uow.commit()
    return SeedResult(workspace.id, created, campaign_created, policies_created)
