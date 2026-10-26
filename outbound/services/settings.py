"""Workspace settings an operator edits: sender profile, campaigns, policies, suppressions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from outbound.db.errors import NotFound
from outbound.db.uow import UnitOfWork, UnitOfWorkFactory
from outbound.domain.actors import OPERATOR
from outbound.domain.entities import Campaign, CountryPolicy, Workspace
from outbound.domain.enums import (
    EntityType,
    PolicyRule,
    Provenance,
    SuppressionKind,
    SuppressionReason,
)
from outbound.services.dns_check import (
    COMMON_DKIM_SELECTORS,
    MxLookup,
    TxtLookup,
    check_domain,
    system_lookup,
    system_mx,
)

SENDER_FIELDS = frozenset(
    {
        "company_name", "domain", "industry", "mission", "value_propositions", "technologies",
        "target_verticals", "case_studies", "geographic_focus", "signature_name",
        "signature_title", "legal_name", "postal_address", "registration_details",
        "contact_info", "narrative", "greeting", "outreach_goal", "style_examples",
    }
)  # fmt: skip
REVIEWED_KEY = "reviewed_at"
# The fixed format of the downloadable profile file: every key, in the order the screen asks them,
# with what an empty one looks like. A file with other keys is refused when it is uploaded.
TEMPLATE_FIELDS: dict[str, Any] = {
    "legal_name": "", "company_name": "", "domain": "", "postal_address": "",
    "registration_details": "", "contact_info": "", "signature_name": "", "signature_title": "",
    "greeting": "Hi", "industry": "", "mission": "", "narrative": "", "geographic_focus": "",
    "value_propositions": [], "technologies": [], "target_verticals": [], "case_studies": [],
    "outreach_goal": "", "style_examples": [],
}  # fmt: skip


def profile_template(current: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The profile file: all the keys, empty (or filled from ``current``)."""
    have = current or {}
    return {key: have.get(key, empty) for key, empty in TEMPLATE_FIELDS.items()}


SETTING_FIELDS = frozenset(
    {
        "safe_to_send_only",
        "budget_per_prospect_micro_usd",
        "few_shot_examples",
        "timezone",
        "country_policy_enabled",  # off: no country rule is applied anywhere (suppression is)
        "footer_enabled",  # off: no footer is added to any email
        "email_min_words",
        "email_max_words",
    }
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
        mx_lookup: MxLookup | None = None,
        actor: str = OPERATOR,
    ) -> None:
        self._uow = uow_factory
        self._workspace_id = workspace_id
        self._dns = dns_lookup
        # MX is looked up for real only when the TXT lookup is the real one too (tests inject both)
        self._mx = (
            mx_lookup
            if mx_lookup is not None
            else (system_mx if dns_lookup is system_lookup else None)
        )
        self._actor = actor

    # ------------------------------------------------------------------ profile and settings

    def sender_profile(self) -> dict[str, Any]:
        with self._uow(self._workspace_id) as uow:
            workspace = uow.workspace()
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
        with self._uow(self._workspace_id) as uow:
            workspace = self._workspace(uow)
            merged = {
                **workspace.sender_profile,
                **changes,
                REVIEWED_KEY: datetime.now(UTC).isoformat(),
            }
            uow.own_workspace.set_sender_profile(merged)
            self._record_change(uow, "sender_profile_reviewed", {"fields": sorted(changes)})
            uow.commit()
        return merged

    def workspace_settings(self) -> dict[str, Any]:
        with self._uow(self._workspace_id) as uow:
            workspace = uow.workspace()
        return dict(workspace.settings) if workspace else {}

    def update_workspace_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        if changes.get("send_enabled"):
            raise SettingsError("automatic sending cannot be switched on until Phase 5's gate")
        unknown = set(changes) - SETTING_FIELDS
        if unknown:
            raise SettingsError(f"cannot change setting(s): {sorted(unknown)}")
        with self._uow(self._workspace_id) as uow:
            workspace = self._workspace(uow)
            merged = {**workspace.settings, **changes}
            low, high = merged.get("email_min_words", 120), merged.get("email_max_words", 200)
            if low > high:
                raise SettingsError(
                    f"the shortest email ({low} words) cannot be longer than the longest ({high})"
                )
            uow.own_workspace.set_settings(merged)
            self._record_change(uow, "settings_changed", changes)
            uow.commit()
        return merged

    @staticmethod
    def _workspace(uow: UnitOfWork) -> Workspace:
        workspace = uow.workspace()
        if workspace is None:
            raise NotFound(f"workspace {uow.workspace_id}")
        return workspace

    def _record_change(self, uow: UnitOfWork, kind: str, detail: dict[str, Any]) -> None:
        """Settings such as the safe-to-send safeguard and the budget are safety controls, so
        who changed them to what is part of the audit trail (the sender profile: only which
        fields, since it holds free text). Written in the same transaction as the change."""
        uow.events.append(EntityType.WORKSPACE, self._workspace_id, kind, self._actor, detail)

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
            # Country rules decide who may be written to, so every change is in the audit trail.
            uow.events.append(
                EntityType.WORKSPACE,
                self._workspace_id,
                "policy_changed",
                self._actor,
                {
                    "country_code": saved.country_code,
                    "rule": saved.rule.value,
                    "requires_corporate_subscriber": saved.requires_corporate_subscriber,
                    "allowed_provenance": [p.value for p in saved.allowed_provenance or ()],
                    "version": saved.version,
                    "reviewed_by": saved.reviewed_by,
                },
            )
            uow.commit()
            return saved

    def delete_policy(self, country_code: str) -> None:
        """Remove a country's rule. Its leads are then held for you (no rule means no guess)."""
        code = country_code.strip().upper()
        with self._uow(self._workspace_id) as uow:
            if not uow.policies.delete(code):
                raise NotFound(f"no rule for {code}")
            uow.events.append(
                EntityType.WORKSPACE,
                self._workspace_id,
                "policy_deleted",
                self._actor,
                {"country_code": code},
            )
            uow.commit()

    # ------------------------------------------------------------------ suppressions

    def suppressions(self) -> list[SuppressionEntry]:
        with self._uow(self._workspace_id) as uow:
            return [
                SuppressionEntry(r.kind, r.reason, r.value_hash[:10], r.created_at)
                for r in uow.suppressions.entries()
            ]

    def suppress(
        self,
        kind: SuppressionKind,
        value: str,
        reason: SuppressionReason,
        *,
        actor: str | None = None,
    ) -> bool:
        """Add a value to the do-not-contact list. It is hashed here and never stored."""
        actor = actor or self._actor
        if not value.strip():
            raise SettingsError("give the address or domain to suppress")
        with self._uow(self._workspace_id) as uow:
            added = uow.suppressions.add(kind, value, reason, actor=actor)
            uow.commit()
            return added

    # ------------------------------------------------------------------ mailboxes

    def dns_check(self, mailbox_id: str) -> dict[str, object]:
        with self._uow(self._workspace_id) as uow:
            mailbox = uow.mailboxes.get(mailbox_id)
        given = (mailbox.connection or {}).get("dkim_selector")  # one the person entered
        report = check_domain(
            mailbox.sending_domain,
            self._dns,
            [*([given] if given else []), *COMMON_DKIM_SELECTORS],
            mx_lookup=self._mx,
            gateway=mailbox.gateway.value,
        ).to_json()
        with self._uow(self._workspace_id) as uow:
            uow.mailboxes.set_dns_check(mailbox_id, report)
            uow.commit()
        return report
