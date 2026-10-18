"""Business rules as plain functions over plain data, so they test without a database.

Three rules live here: the country policy (can we contact this lead at all?), the safe-to-send
check (may this exact message go out right now?), and the fit gate. They are applied at the
gate stage and again just before every draft or send.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from outbound.domain.entities import CountryPolicy
from outbound.domain.enums import (
    CompanySource,
    ContactStatus,
    EmailStatus,
    HoldReason,
    LegalEntityType,
    PolicyRule,
    Provenance,
)

UNKNOWN_COUNTRY = "ZZ"

# Leads the operator chose by hand skip the fit gate (their score is still recorded).
OPERATOR_CHOSEN = frozenset({CompanySource.MANUAL, CompanySource.IMPORT, CompanySource.REFERRAL})


class PolicyOutcome(StrEnum):
    ALLOW = "allow"
    HOLD = "hold"  # wait for a person: consent, a reviewed rule, a confirmed legal entity
    BLOCK = "block"  # never contact


@dataclass(frozen=True)
class PolicyDecision:
    outcome: PolicyOutcome
    reasons: tuple[str, ...]
    hold_reason: HoldReason | None = None
    rule: PolicyRule | None = None
    footer_template: str | None = None
    policy_version: int | None = None

    def to_json(self) -> dict[str, Any]:
        """The shape stored in ``companies.policy_decision`` for later audit."""
        return {
            "outcome": self.outcome.value,
            "rule": self.rule.value if self.rule else None,
            "hold_reason": self.hold_reason.value if self.hold_reason else None,
            "policy_version": self.policy_version,
            "reasons": list(self.reasons),
        }


def decide_country_policy(
    *,
    country_code: str | None,
    legal_entity_type: LegalEntityType,
    policy: CountryPolicy | None,
    email_provenance: Provenance | None = None,
    has_active_consent: bool = False,
) -> PolicyDecision:
    """Can this lead be contacted? ``email_provenance`` is None before an email exists.

    A recorded consent overrides every hold and block, because that is what consent is for,
    but an unknown country is still held: without a country there is no footer to attach.
    """
    if not country_code or country_code.upper() == UNKNOWN_COUNTRY:
        return PolicyDecision(
            PolicyOutcome.HOLD, ("country unknown",), hold_reason=HoldReason.COUNTRY_UNKNOWN
        )
    if policy is None:
        return PolicyDecision(
            PolicyOutcome.HOLD,
            (f"no policy row for {country_code.upper()}: add and review one",),
            hold_reason=HoldReason.NEEDS_OPERATOR,
        )

    def verdict(
        outcome: PolicyOutcome, *reasons: str, hold: HoldReason | None = None
    ) -> PolicyDecision:
        return PolicyDecision(
            outcome,
            reasons,
            hold_reason=hold,
            rule=policy.rule,
            footer_template=policy.footer_template,
            policy_version=policy.version,
        )

    consented = ("allowed by a recorded consent",) if has_active_consent else ()

    if policy.rule is PolicyRule.BLOCK:
        if has_active_consent:
            return verdict(PolicyOutcome.ALLOW, *consented)
        return verdict(PolicyOutcome.BLOCK, f"{policy.country_code} does not allow cold email")

    if policy.requires_corporate_subscriber and (
        legal_entity_type is not LegalEntityType.CORPORATE_SUBSCRIBER
    ):
        if has_active_consent:
            return verdict(PolicyOutcome.ALLOW, *consented)
        if legal_entity_type is LegalEntityType.UNKNOWN:
            return verdict(
                PolicyOutcome.HOLD,
                "legal entity not confirmed as an incorporated company",
                hold=HoldReason.ENTITY_UNKNOWN,
            )
        return verdict(
            PolicyOutcome.HOLD,
            "sole traders and ordinary partnerships need consent",
            hold=HoldReason.CONSENT_REQUIRED,
        )

    if (
        email_provenance is not None
        and policy.allowed_provenance is not None
        and email_provenance not in policy.allowed_provenance
    ):
        if has_active_consent:
            return verdict(PolicyOutcome.ALLOW, *consented)
        return verdict(
            PolicyOutcome.HOLD,
            f"an address from {email_provenance.value} is not allowed here",
            hold=HoldReason.CONSENT_REQUIRED,
        )

    if policy.rule is PolicyRule.CONSENT_REQUIRED and not has_active_consent:
        return verdict(
            PolicyOutcome.HOLD, "prior consent is required", hold=HoldReason.CONSENT_REQUIRED
        )
    return verdict(PolicyOutcome.ALLOW, *consented)


def is_safe_email_status(status: EmailStatus, *, safe_to_send_only: bool = True) -> bool:
    """``valid`` and ``catch_all_resolved`` are safe. An unresolved catch-all is safe only if the
    workspace has turned the safeguard off."""
    if status in (EmailStatus.VALID, EmailStatus.CATCH_ALL_RESOLVED):
        return True
    return status is EmailStatus.CATCH_ALL_UNVERIFIED and not safe_to_send_only


@dataclass(frozen=True)
class SendVerdict:
    ok: bool
    reasons: tuple[str, ...]


def check_send(
    *,
    email_status: EmailStatus,
    contact_status: ContactStatus,
    email_suppressed: bool,
    domain_suppressed: bool,
    policy_decision: PolicyDecision,
    safe_to_send_only: bool = True,
) -> SendVerdict:
    """All four conditions of the safe-to-send rule; every failing reason is reported."""
    reasons: list[str] = []
    if not is_safe_email_status(email_status, safe_to_send_only=safe_to_send_only):
        reasons.append(f"email status is {email_status.value}")
    if email_suppressed:
        reasons.append("email address is suppressed")
    if domain_suppressed:
        reasons.append("domain is suppressed")
    if policy_decision.outcome is not PolicyOutcome.ALLOW:
        reasons.append(f"country policy: {policy_decision.outcome.value}")
    if contact_status not in (ContactStatus.CANDIDATE, ContactStatus.ACTIVE):
        reasons.append(f"contact is {contact_status.value}")
    return SendVerdict(ok=not reasons, reasons=tuple(reasons))


def passes_fit_gate(*, source: CompanySource, fit_score: int | None, min_fit_score: int) -> bool:
    if source in OPERATOR_CHOSEN:
        return True
    return fit_score is not None and fit_score >= min_fit_score
