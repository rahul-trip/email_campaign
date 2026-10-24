"""Creating a workspace (Phase 6c): the one place that decides what a new one starts with.

A new workspace gets the company's name and website, the default settings, the country rules
and one empty campaign. No profile text, no ideal customer, no signature: the customer writes
those during onboarding, and nothing is drafted until the profile is confirmed.
"""

from __future__ import annotations

from outbound.db.platform import PlatformUnitOfWorkFactory
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.entities import Workspace
from outbound.domain.policy_seeds import DEFAULT_COUNTRY_POLICIES
from outbound.services import defaults


def create_workspace(
    uow: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory, name: str, *, website: str = ""
) -> Workspace:
    """A new workspace, ready for its first admin to set up. Its address (slug) comes from the
    name and is made unique."""
    with platform() as directory:
        created = directory.workspaces.create(
            name.strip(),
            defaults.blank_sender_profile(name, website),
            defaults.default_workspace_settings(),
        )
        directory.commit()
    add_starting_rows(uow, created.id)
    return created


def add_starting_rows(uow: UnitOfWorkFactory, workspace_id: str) -> tuple[int, bool]:
    """The country rules and the empty default campaign, each added only if missing. Returns
    how many rules and whether the campaign were added."""
    with uow(workspace_id) as session:
        rules = sum(session.policies.add_if_missing(policy) for policy in DEFAULT_COUNTRY_POLICIES)
        campaign_added = session.campaigns.by_name(defaults.DEFAULT_CAMPAIGN_NAME) is None
        if campaign_added:
            session.campaigns.create(defaults.DEFAULT_CAMPAIGN_NAME, [])
        session.commit()
    return rules, campaign_added
