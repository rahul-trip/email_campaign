from __future__ import annotations

from outbound.db.platform import PlatformUnitOfWorkFactory
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import PolicyRule
from outbound.domain.policy_seeds import DEFAULT_COUNTRY_POLICIES
from outbound.services import defaults
from outbound.services.seed import seed_defaults


def test_seeding_creates_the_workspace_an_empty_campaign_and_every_policy(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    result = seed_defaults(factory, platform)
    assert result.workspace_created and result.campaign_created
    assert result.policies_created == len(DEFAULT_COUNTRY_POLICIES) == 11
    with factory(result.workspace_id) as uow:
        assert {p.country_code for p in uow.policies.all()} == {
            "US", "GB", "DE", "AT", "FR", "NL", "IE", "SE", "CA", "IN", "ZZ",
        }  # fmt: skip
        campaign = uow.campaigns.by_name(defaults.DEFAULT_CAMPAIGN_NAME)
        assert campaign is not None and campaign.target_titles == ()  # the customer fills these
        assert all(p.version == 1 and p.reviewed_by is None for p in uow.policies.all())


def test_seeding_twice_leaves_exactly_one_of_everything(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    first = seed_defaults(factory, platform)
    second = seed_defaults(factory, platform)
    assert second.workspace_id == first.workspace_id
    assert not second.workspace_created and not second.campaign_created
    assert second.policies_created == 0
    with platform() as directory:
        assert len(directory.workspaces.all()) == 1
    with factory(first.workspace_id) as uow:
        assert len(uow.policies.all()) == 11


def test_seeding_never_overwrites_a_policy_someone_edited(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    workspace_id = seed_defaults(factory, platform).workspace_id
    with factory(workspace_id) as uow:
        row = uow.policies.get("DE")
        assert row is not None and row.rule is PolicyRule.BLOCK
        uow.session.execute(
            __import__("sqlalchemy").text(
                "UPDATE country_policies SET rule = 'allow_with_footer', version = 2 "
                "WHERE country_code = 'DE'"
            )
        )
        uow.commit()
    seed_defaults(factory, platform)
    with factory(workspace_id) as uow:
        edited = uow.policies.get("DE")
        assert edited is not None and edited.rule is PolicyRule.ALLOW_WITH_FOOTER
        assert edited.version == 2


def test_the_default_workspace_keeps_automatic_sending_off(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    workspace_id = seed_defaults(factory, platform).workspace_id
    with factory(workspace_id) as uow:
        workspace = uow.workspace()
    assert workspace is not None
    assert workspace.settings["send_enabled"] is False
    assert workspace.settings["safe_to_send_only"] is True
    assert workspace.settings["budget_per_prospect_micro_usd"] == 500_000
    # The footers need these, and they are blank until the operator fills them in.
    assert workspace.sender_profile["postal_address"] == ""
    assert workspace.sender_profile["narrative"] == ""  # nothing is pre-written for the writer


def test_a_second_workspace_gets_its_own_policies(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    one = seed_defaults(factory, platform, "one")
    two = seed_defaults(factory, platform, "two")
    assert one.workspace_id != two.workspace_id
    assert two.workspace_created and two.policies_created == 11


def test_a_created_workspace_is_independent_and_blank(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    from outbound.services.workspaces import create_workspace

    one = create_workspace(factory, platform, "Globex Ltd", website="globex.example")
    two = create_workspace(factory, platform, "Globex Ltd")  # a name may repeat
    assert (one.slug, two.slug) == ("globex-ltd", "globex-ltd-2")
    with factory(one.id) as uow:
        workspace = uow.workspace()
        assert workspace is not None and workspace.sender_profile["domain"] == "globex.example"
        assert "Quantra" not in str(workspace.sender_profile)
        assert len(uow.policies.all()) == 11
        [campaign] = uow.campaigns.all()
        assert campaign.target_titles == () and campaign.icp_description is None
    with platform() as directory:
        assert len(directory.workspaces.all()) == 2  # nothing stray was created
