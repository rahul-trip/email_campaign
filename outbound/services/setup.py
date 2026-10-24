"""What a workspace still has to do before the engine works well (Phase 6c).

One list, computed on the server from what is saved, so the Dashboard's "Get started", the
Settings check and the onboarding wizard all say the same thing. Each item is ``ok``,
``warning`` (works, but should be looked at) or ``missing`` (nothing can be drafted until it is
done), with where to fix it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import MailboxStatus, PolicyRule
from outbound.domain.sender import sender_for

Status = Literal["ok", "warning", "missing"]
MAILBOX = "A mailbox connected"


@dataclass(frozen=True)
class SetupItem:
    key: str
    title: str
    status: Status
    detail: str
    where: str  # settings:profile, settings:mailboxes, campaigns, compliance or targets


@dataclass(frozen=True)
class SetupReport:
    items: list[SetupItem]

    @property
    def done(self) -> bool:
        return all(i.status != "missing" for i in self.items)

    @property
    def next(self) -> SetupItem | None:
        return next((i for i in self.items if i.status == "missing"), None)


def _has(source: Mapping[str, Any], key: str) -> bool:
    return bool(str(source.get(key) or "").strip())


def _item(
    key: str, title: str, ok: bool, good: str, bad: str, where: str, *, required: bool = True
) -> SetupItem:
    """``ok``, else ``missing`` when it blocks drafting and ``warning`` when it does not."""
    status: Status = "ok" if ok else ("missing" if required else "warning")
    return SetupItem(key, title, status, good if ok else bad, where)


class SetupService:
    def __init__(self, uow_factory: UnitOfWorkFactory, workspace_id: str) -> None:
        self._uow = uow_factory
        self._workspace_id = workspace_id

    def report(self) -> SetupReport:
        with self._uow(self._workspace_id) as uow:
            workspace = uow.workspace()
            profile = dict(workspace.sender_profile) if workspace else {}
            mailboxes = uow.mailboxes.all()
            campaigns = uow.campaigns.all()
            policies = uow.policies.all()
            leads = uow.companies.search()[1]

        default = next((m for m in mailboxes if m.is_default), None) or next(iter(mailboxes), None)
        sender = sender_for(profile, default.sender if default else None)
        ready = next((c for c in campaigns if c.target_titles and c.icp_description), None)
        working = [m for m in mailboxes if m.status is MailboxStatus.ACTIVE]
        checked = [m.dns_check for m in working if m.dns_check]
        dns_ok = bool(checked) and all(report.get("ok") for report in checked)
        unreviewed = [
            p.country_code for p in policies if p.rule is not PolicyRule.BLOCK and not p.reviewed_by
        ]

        if working:
            mailbox_state = _item(
                "mailbox", MAILBOX, True, f"{len(working)} working.", "", "settings:mailboxes"
            )
        elif mailboxes:
            mailbox_state = SetupItem(
                "mailbox", MAILBOX, "warning",
                "Every mailbox is paused or needs connecting again.", "settings:mailboxes",
            )  # fmt: skip
        else:
            mailbox_state = _item(
                "mailbox", MAILBOX, False, "",
                "Drafts are saved in a mailbox you connect; until then approved emails wait.",
                "settings:mailboxes",
            )  # fmt: skip

        return SetupReport([
            _item("profile", "Company profile confirmed", bool(profile.get("reviewed_at")),
                  "Confirmed.",
                  "Describe your company and confirm it: no email is written until you do.",
                  "settings:profile"),
            _item("legal", "Legal name and postal address",
                  _has(profile, "legal_name") and _has(profile, "postal_address"),
                  "Filled in.",
                  "Every country's footer prints them; a footer with a gap stops the email.",
                  "settings:profile"),
            _item("signature", "Who signs the emails",
                  _has(sender, "signature_name") and _has(sender, "signature_title"),
                  "Set.", "A name and title end every email (set per mailbox, or for the company).",
                  "settings:profile"),
            _item("campaign", "A campaign with job titles and an ideal customer", ready is not None,
                  f'"{ready.name}" is ready.' if ready else "",
                  "Without them people cannot be ranked and fit cannot be scored.", "campaigns"),
            mailbox_state,
            _item("dns", "Mailbox domain authentication checked", dns_ok,
                  "SPF, DKIM and DMARC look right.",
                  "Some checks failed: open Mailboxes for what to fix." if checked
                  else "Check SPF, DKIM and DMARC so your emails are not treated as spam.",
                  "settings:mailboxes", required=False),
            _item("rules", "Country rules reviewed", not unreviewed,
                  "Every country that allows email has a named reviewer.",
                  f"Reviewer missing for {', '.join(unreviewed)}. A lawyer should check them.",
                  "compliance", required=False),
            _item("leads", "First leads added", leads > 0, f"{leads} lead(s).",
                  "Add a few companies to start.", "targets", required=False),
        ])  # fmt: skip
