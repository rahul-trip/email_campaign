"""One test per row of the plan's compliance table, run against the seeded policies."""

from __future__ import annotations

import pytest

from outbound.domain.enums import (
    CompanySource,
    ContactStatus,
    EmailStatus,
    HoldReason,
    LegalEntityType,
    PolicyRule,
    Provenance,
)
from outbound.domain.policies import (
    PolicyDecision,
    PolicyOutcome,
    check_send,
    decide_country_policy,
    is_safe_email_status,
    passes_fit_gate,
)
from outbound.domain.policy_seeds import DEFAULT_COUNTRY_POLICIES

POLICIES = {p.country_code: p for p in DEFAULT_COUNTRY_POLICIES}
CORPORATE = LegalEntityType.CORPORATE_SUBSCRIBER
SOLE = LegalEntityType.SOLE_TRADER_OR_PARTNERSHIP
UNKNOWN = LegalEntityType.UNKNOWN


def decide(
    country: str | None,
    entity: LegalEntityType = UNKNOWN,
    provenance: Provenance | None = None,
    consent: bool = False,
) -> PolicyDecision:
    return decide_country_policy(
        country_code=country,
        legal_entity_type=entity,
        policy=POLICIES.get(country.upper()) if country else None,
        email_provenance=provenance,
        has_active_consent=consent,
    )


def test_us_is_allowed_with_a_footer() -> None:
    result = decide("US")
    assert result.outcome is PolicyOutcome.ALLOW
    assert result.rule is PolicyRule.ALLOW_WITH_FOOTER
    assert "{postal_address}" in (result.footer_template or "")
    assert result.policy_version == 1


def test_uk_corporate_subscriber_is_allowed() -> None:
    assert decide("GB", CORPORATE).outcome is PolicyOutcome.ALLOW


def test_uk_with_an_unconfirmed_legal_entity_is_held_for_entity() -> None:
    result = decide("GB", UNKNOWN)
    assert result.outcome is PolicyOutcome.HOLD
    assert result.hold_reason is HoldReason.ENTITY_UNKNOWN


def test_uk_sole_trader_is_held_for_consent() -> None:
    result = decide("GB", SOLE)
    assert (result.outcome, result.hold_reason) == (PolicyOutcome.HOLD, HoldReason.CONSENT_REQUIRED)


def test_uk_sole_trader_with_recorded_consent_is_allowed() -> None:
    assert decide("GB", SOLE, consent=True).outcome is PolicyOutcome.ALLOW


@pytest.mark.parametrize("country", ["DE", "AT"])
def test_germany_and_austria_are_blocked_unless_consent_is_recorded(country: str) -> None:
    assert decide(country, CORPORATE).outcome is PolicyOutcome.BLOCK
    assert decide(country, CORPORATE, consent=True).outcome is PolicyOutcome.ALLOW


@pytest.mark.parametrize("country", ["FR", "NL", "IE", "SE"])
def test_permissive_eu_countries_are_allowed_with_a_footer(country: str) -> None:
    result = decide(country)
    assert result.outcome is PolicyOutcome.ALLOW
    assert result.footer_template


def test_an_eu_country_without_a_reviewed_row_is_held_for_an_operator() -> None:
    result = decide("ES")
    assert (result.outcome, result.hold_reason) == (PolicyOutcome.HOLD, HoldReason.NEEDS_OPERATOR)
    assert "ES" in result.reasons[0]


@pytest.mark.parametrize("provenance", [Provenance.OPERATOR_GIVEN, Provenance.PUBLICLY_PUBLISHED])
def test_canada_allows_published_or_operator_given_addresses(provenance: Provenance) -> None:
    assert decide("CA", provenance=provenance).outcome is PolicyOutcome.ALLOW


@pytest.mark.parametrize(
    "provenance", [Provenance.PATTERN_INFERRED, Provenance.API_DATABASE, Provenance.REFERRAL]
)
def test_canada_holds_guessed_or_database_addresses(provenance: Provenance) -> None:
    result = decide("CA", provenance=provenance)
    assert (result.outcome, result.hold_reason) == (PolicyOutcome.HOLD, HoldReason.CONSENT_REQUIRED)


def test_canada_cannot_judge_provenance_before_an_email_exists() -> None:
    assert decide("CA", provenance=None).outcome is PolicyOutcome.ALLOW


def test_canada_guessed_address_is_allowed_with_consent() -> None:
    assert (
        decide("CA", provenance=Provenance.PATTERN_INFERRED, consent=True).outcome
        is PolicyOutcome.ALLOW
    )


def test_india_is_held_for_consent_until_consent_is_recorded() -> None:
    held = decide("IN")
    assert (held.outcome, held.hold_reason) == (PolicyOutcome.HOLD, HoldReason.CONSENT_REQUIRED)
    assert decide("IN", consent=True).outcome is PolicyOutcome.ALLOW


@pytest.mark.parametrize("country", [None, "", "ZZ", "zz"])
def test_an_unknown_country_is_held_even_when_consent_exists(country: str | None) -> None:
    for consent in (False, True):
        result = decide(country, consent=consent)
        assert (result.outcome, result.hold_reason) == (
            PolicyOutcome.HOLD,
            HoldReason.COUNTRY_UNKNOWN,
        )


def test_the_decision_serialises_for_the_audit_column() -> None:
    assert decide("GB", UNKNOWN).to_json() == {
        "outcome": "hold",
        "rule": "allow_with_footer",
        "hold_reason": "entity_unknown",
        "policy_version": 1,
        "reasons": ["legal entity not confirmed as an incorporated company"],
        "skipped": False,
    }


# ------------------------------------------------------------------ safe to send

ALLOW = decide("US")


@pytest.mark.parametrize(
    ("status", "safeguard", "safe"),
    [
        (EmailStatus.VALID, True, True),
        (EmailStatus.CATCH_ALL_RESOLVED, True, True),
        (EmailStatus.CATCH_ALL_UNVERIFIED, True, False),
        (EmailStatus.CATCH_ALL_UNVERIFIED, False, True),
        (EmailStatus.CATCH_ALL_PENDING, False, False),
        (EmailStatus.UNVERIFIED, False, False),
        (EmailStatus.UNKNOWN, False, False),
        (EmailStatus.INVALID, False, False),
    ],
)
def test_which_email_statuses_are_safe(status: EmailStatus, safeguard: bool, safe: bool) -> None:
    assert is_safe_email_status(status, safe_to_send_only=safeguard) is safe


def send(**overrides: object) -> bool:
    args: dict[str, object] = {
        "email_status": EmailStatus.VALID,
        "contact_status": ContactStatus.ACTIVE,
        "email_suppressed": False,
        "domain_suppressed": False,
        "policy_decision": ALLOW,
    }
    return check_send(**{**args, **overrides}).ok  # type: ignore[arg-type]


def test_a_clean_message_may_be_sent() -> None:
    assert send()


@pytest.mark.parametrize(
    "override",
    [
        {"email_status": EmailStatus.CATCH_ALL_UNVERIFIED},
        {"email_suppressed": True},
        {"domain_suppressed": True},
        {"policy_decision": decide("DE", CORPORATE)},
        {"policy_decision": decide("IN")},
        {"contact_status": ContactStatus.BOUNCED},
        {"contact_status": ContactStatus.FORGOTTEN},
    ],
)
def test_any_single_failing_condition_stops_the_send(override: dict[str, object]) -> None:
    assert not send(**override)


def test_every_failing_reason_is_reported() -> None:
    verdict = check_send(
        email_status=EmailStatus.INVALID,
        contact_status=ContactStatus.OPTED_OUT,
        email_suppressed=True,
        domain_suppressed=True,
        policy_decision=decide("DE", CORPORATE),
    )
    assert not verdict.ok
    assert len(verdict.reasons) == 5


# ------------------------------------------------------------------ fit gate


@pytest.mark.parametrize(
    "source", [CompanySource.MANUAL, CompanySource.IMPORT, CompanySource.REFERRAL]
)
def test_leads_the_operator_chose_skip_the_fit_gate(source: CompanySource) -> None:
    assert passes_fit_gate(source=source, fit_score=5, min_fit_score=60)
    assert passes_fit_gate(source=source, fit_score=None, min_fit_score=60)


@pytest.mark.parametrize(("score", "passes"), [(60, True), (59, False), (100, True), (None, False)])
def test_discovered_leads_need_the_minimum_score(score: int | None, passes: bool) -> None:
    assert (
        passes_fit_gate(source=CompanySource.DISCOVERY, fit_score=score, min_fit_score=60) is passes
    )
