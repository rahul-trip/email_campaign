"""The setup report (Phase 6c): what a workspace still has to do, from what is saved."""

from __future__ import annotations

from outbound.db.platform import PlatformUnitOfWorkFactory
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import MailboxStatus
from outbound.services.setup import SetupService
from outbound.services.workspaces import create_workspace
from tests.stages.world import PROFILE


def statuses(factory: UnitOfWorkFactory, ws: str) -> dict[str, str]:
    return {i.key: i.status for i in SetupService(factory, ws).report().items}


def test_a_new_workspace_has_everything_to_do_and_the_next_step_is_the_profile(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws = create_workspace(factory, platform, "Globex Ltd").id
    report = SetupService(factory, ws).report()
    assert {i.key: i.status for i in report.items} == {
        "profile": "missing", "legal": "missing", "signature": "missing", "campaign": "missing",
        "mailbox": "missing", "dns": "warning", "rules": "warning", "leads": "warning",
    }  # fmt: skip
    assert not report.done and report.next is not None and report.next.key == "profile"
    assert report.next.where == "settings:profile"


def test_a_filled_in_workspace_with_a_working_mailbox_is_done(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws = create_workspace(factory, platform, "Globex Ltd").id
    with factory(ws) as uow:
        uow.own_workspace.set_sender_profile(
            {**PROFILE, "reviewed_at": "2026-10-24T00:00:00+00:00"}
        )
        [campaign] = uow.campaigns.all()
        uow.campaigns.update(
            campaign.id, {"target_titles": ["CTO"], "icp_description": "Utilities"}
        )
        box = uow.mailboxes.create("sam@globex.example", "globex.example")
        uow.mailboxes.set_dns_check(box.id, {"ok": True})
        uow.commit()
    report = SetupService(factory, ws).report()
    assert report.done and report.next is None
    assert statuses(factory, ws)["mailbox"] == "ok" and statuses(factory, ws)["dns"] == "ok"


def test_the_signature_can_come_from_the_default_mailbox(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws = create_workspace(factory, platform, "Globex Ltd").id
    with factory(ws) as uow:
        uow.mailboxes.create(
            "pat@globex.example", "globex.example",
            sender={"signature_name": "Pat Kim", "signature_title": "Head of Sales"},
        )  # fmt: skip
        uow.commit()
    assert statuses(factory, ws)["signature"] == "ok"


def test_mailboxes_that_cannot_be_used_are_a_warning_not_a_blocker_of_the_profile(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    ws = create_workspace(factory, platform, "Globex Ltd").id
    with factory(ws) as uow:
        box = uow.mailboxes.create("sam@globex.example", "globex.example")
        uow.mailboxes.update(box.id, status=MailboxStatus.NEEDS_RECONNECT)
        uow.commit()
    report = SetupService(factory, ws).report()
    mailbox = next(i for i in report.items if i.key == "mailbox")
    assert mailbox.status == "warning" and "needs connecting" in mailbox.detail


def test_failed_dns_checks_are_named_and_a_workspaces_report_ignores_other_workspaces(
    factory: UnitOfWorkFactory, platform: PlatformUnitOfWorkFactory
) -> None:
    one = create_workspace(factory, platform, "One").id
    two = create_workspace(factory, platform, "Two").id
    with factory(one) as uow:
        box = uow.mailboxes.create("a@one.example", "one.example")
        uow.mailboxes.set_dns_check(box.id, {"ok": False})
        uow.commit()
    assert statuses(factory, one)["dns"] == "warning"
    assert (
        "failed"
        in next(i for i in SetupService(factory, one).report().items if i.key == "dns").detail
    )
    assert statuses(factory, two)["mailbox"] == "missing"
