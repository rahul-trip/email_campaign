"""Workspace settings an operator edits: sender profile, campaigns, policies, suppressions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from outbound.db.repositories.workspaces import MailboxView
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.actors import OPERATOR
from outbound.domain.entities import Campaign, CountryPolicy
from outbound.domain.enums import (
    PolicyRule,
    Provenance,
    SuppressionKind,
    SuppressionReason,
)
from outbound.services.dns_check import TxtLookup, check_domain, system_lookup

SENDER_FIELDS = frozenset(
    {
        "company_name", "domain", "industry", "mission", "value_propositions", "technologies",
        "target_verticals", "case_studies", "geographic_focus", "signature_name",
        "signature_title", "legal_name", "postal_address", "registration_details",
        "contact_info", "narrative",
    }
)  # fmt: skip
REVIEWED_KEY = "reviewed_at"
SETTING_FIELDS = frozenset(
    {"safe_to_send_only", "budget_per_prospect_micro_usd", "few_shot_examples", "timezone"}
)


class SettingsError(Exception):
    """The change is not allowed; the message says why."""


@dataclass(frozen=True)
class SuppressionEntry:
    kind: SuppressionKind
    reason: SuppressionReason
    fingerprint: str  # the start of the hash: enough to tell entries apart, no personal data
    created_at: datetime


class SettingsService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        workspace_id: str,
        *,
        dns_lookup: TxtLookup = system_lookup,
    ) -> None:
        self._uow = uow_factory
        self._workspace_id = workspace_id
        self._dns = dns_lookup

    # ------------------------------------------------------------------ profile and settings

    def sender_profile(self) -> dict[str, Any]:
        with self._uow.admin() as admin:
            workspace = admin.workspaces.get(self._workspace_id)
        return dict(workspace.sender_profile) if workspace else {}

    def update_sender_profile(self, changes: dict[str, Any]) -> dict[str, Any]:
        """Merge ``changes`` into the profile and record that the operator has reviewed it.

        Every save is a review: the screen and the command line both ask the operator to
        confirm that each statement is true. ``reviewed_at`` is ours to set, never the client's.
        """
        changes = {k: v for k, v in changes.items() if k != REVIEWED_KEY}
        unknown = set(changes) - SENDER_FIELDS
        if unknown:
            raise SettingsError(f"unknown sender profile field(s): {sorted(unknown)}")
        with self._uow.admin() as admin:
            workspace = admin.workspaces.get(self._workspace_id)
            assert workspace is not None
            merged = {
                **workspace.sender_profile,
                **changes,
                REVIEWED_KEY: datetime.now(UTC).isoformat(),
            }
            admin.workspaces.set_sender_profile(self._workspace_id, merged)
            admin.commit()
        return merged

    def workspace_settings(self) -> dict[str, Any]:
        with self._uow.admin() as admin:
            workspace = admin.workspaces.get(self._workspace_id)
        return dict(workspace.settings) if workspace else {}

    def update_workspace_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        if changes.get("send_enabled"):
            raise SettingsError("automatic sending cannot be switched on until Phase 5's gate")
        unknown = set(changes) - SETTING_FIELDS
        if unknown:
            raise SettingsError(f"cannot change setting(s): {sorted(unknown)}")
        with self._uow.admin() as admin:
            workspace = admin.workspaces.get(self._workspace_id)
            assert workspace is not None
            merged = {**workspace.settings, **changes}
            admin.workspaces.set_settings(self._workspace_id, merged)
            admin.commit()
        return merged

    # ------------------------------------------------------------------ campaigns

    def campaigns(self) -> list[Campaign]:
        with self._uow(self._workspace_id) as uow:
            return uow.campaigns.all()

    def create_campaign(self, name: str, target_titles: list[str], **fields: Any) -> Campaign:
        if not name.strip() or not target_titles:
            raise SettingsError("a campaign needs a name and at least one wanted job title")
        with self._uow(self._workspace_id) as uow:
            if uow.campaigns.by_name(name.strip()):
                raise SettingsError(f"a campaign named {name.strip()!r} already exists")
            created = uow.campaigns.create(name.strip(), target_titles, **fields)
            uow.commit()
            return created

    def update_campaign(self, campaign_id: str, changes: dict[str, Any]) -> Campaign:
        try:
            with self._uow(self._workspace_id) as uow:
                updated = uow.campaigns.update(campaign_id, changes)
                uow.commit()
                return updated
        except ValueError as error:
            raise SettingsError(str(error)) from None

    # ------------------------------------------------------------------ country policies

    def policies(self) -> list[CountryPolicy]:
        with self._uow(self._workspace_id) as uow:
            return uow.policies.all()

    def save_policy(
        self,
        country_code: str,
        rule: PolicyRule,
        *,
        requires_corporate_subscriber: bool = False,
        allowed_provenance: list[Provenance] | None = None,
        footer_template: str | None = None,
        reviewer: str | None = None,
    ) -> CountryPolicy:
        if len(country_code.strip()) != 2:
            raise SettingsError("a country is its two-letter ISO code, for example GB")
        policy = CountryPolicy(
            country_code=country_code.strip().upper(),
            rule=rule,
            requires_corporate_subscriber=requires_corporate_subscriber,
            allowed_provenance=tuple(allowed_provenance)
            if allowed_provenance is not None
            else None,
            footer_template=footer_template,
        )
        with self._uow(self._workspace_id) as uow:
            saved = uow.policies.upsert(policy, reviewer=reviewer)
            uow.commit()
            return saved

    # ------------------------------------------------------------------ suppressions

    def suppressions(self) -> list[SuppressionEntry]:
        with self._uow(self._workspace_id) as uow:
            return [
                SuppressionEntry(r.kind, r.reason, r.value_hash[:10], r.created_at)
                for r in uow.suppressions.entries()
            ]

    def suppress(
        self, kind: SuppressionKind, value: str, reason: SuppressionReason, *, actor: str = OPERATOR
    ) -> bool:
        """Add a value to the do-not-contact list. It is hashed here and never stored."""
        if not value.strip():
            raise SettingsError("give the address or domain to suppress")
        with self._uow(self._workspace_id) as uow:
            added = uow.suppressions.add(kind, value, reason, actor=actor)
            uow.commit()
            return added

    # ------------------------------------------------------------------ mailboxes

    def mailboxes(self) -> list[MailboxView]:
        with self._uow(self._workspace_id) as uow:
            return uow.mailboxes.all()

    def add_mailbox(
        self, address: str, credentials_ref: str, *, daily_cap: int = 10
    ) -> MailboxView:
        if "@" not in address:
            raise SettingsError("a mailbox is an email address")
        domain = address.rsplit("@", 1)[1]
        with self._uow(self._workspace_id) as uow:
            created = uow.mailboxes.create(address, domain, credentials_ref, daily_cap=daily_cap)
            uow.commit()
            return created

    def dns_check(self, mailbox_id: str) -> dict[str, object]:
        with self._uow(self._workspace_id) as uow:
            mailbox = uow.mailboxes.get(mailbox_id)
        report = check_domain(mailbox.sending_domain, self._dns).to_json()
        with self._uow(self._workspace_id) as uow:
            uow.mailboxes.set_dns_check(mailbox_id, report)
            uow.commit()
        return report
