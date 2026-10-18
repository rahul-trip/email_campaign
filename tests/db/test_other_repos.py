from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from outbound.db.errors import ConcurrencyConflict
from outbound.db.types import utcnow
from outbound.db.uow import UnitOfWork, UnitOfWorkFactory
from outbound.domain.entities import CountryPolicy, Message
from outbound.domain.enums import (
    CallOutcome,
    CompanySource,
    ContactSource,
    ImportAnchor,
    ImportRowStatus,
    ImportSource,
    MessageState,
    PolicyRule,
    Provenance,
    RunKind,
    RunStatus,
    SuppressionKind,
    SuppressionReason,
)
from outbound.domain.state_machines import IllegalTransition

M = MessageState


def message(uow: UnitOfWork, step: int = 0, **kwargs: object) -> tuple[Message, str, str]:
    """A message plus its company and contact ids, creating the company, contact and address."""
    company = uow.companies.by_domain("acme.com") or uow.companies.create(
        domain="acme.com", source=CompanySource.MANUAL
    )
    contacts = uow.contacts.for_company(company.id)
    person = (
        contacts[0] if contacts else uow.contacts.add(company.id, rank=1, source=ContactSource.SITE)
    )
    address = uow.emails.by_address("jane@acme.com") or uow.emails.add(
        person.id, "jane@acme.com", Provenance.API_DATABASE
    )
    created = uow.messages.create(
        company_id=company.id,
        contact_id=person.id,
        contact_email_id=address.id,
        step=step,
        subject="forecast error at acme",
        generated_body="Hi Jane",
        **kwargs,  # type: ignore[arg-type]
    )
    return created, company.id, person.id


# ------------------------------------------------------------------ messages


def test_a_message_starts_generated_and_keeps_both_texts(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        created, company_id, _ = message(uow, snippets={"hook": "x"}, lint_report={"ok": True})
        uow.commit()
        assert created.state is M.GENERATED
        assert created.final_body is None and created.generated_body == "Hi Jane"
        assert uow.messages.for_company(company_id) == [created]


def test_there_is_one_message_per_touch_per_contact(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        message(uow, step=0)
        with pytest.raises(IntegrityError):
            message(uow, step=0)


def test_touches_beyond_the_third_are_refused(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow, pytest.raises(IntegrityError):
        message(uow, step=3)


def test_a_message_moves_through_approval_draft_and_send(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    sent_at = utcnow()
    with factory(ws) as uow:
        created, _, _ = message(uow)
        approved = uow.messages.transition(
            created.id, M.APPROVED, expected_version=created.row_version
        )
        drafted = uow.messages.transition(
            approved.id, M.DRAFTED, expected_version=approved.row_version,
            set_fields={"remote_draft_id": "imap-uid-7"},
        )  # fmt: skip
        details = {
            "rfc_message_id": "<abc@mail>",
            "sent_at": sent_at,
            "final_body": "Hi Jane!",
            "edit_distance": 0.04,
        }
        sent = uow.messages.transition(
            drafted.id, M.SENT, expected_version=drafted.row_version, set_fields=details
        )
        assert (sent.state, sent.rfc_message_id, sent.final_body, sent.edit_distance) == (
            M.SENT, "<abc@mail>", "Hi Jane!", 0.04,
        )  # fmt: skip
        assert sent.remote_draft_id == "imap-uid-7"


def test_illegal_message_moves_and_unknown_fields_are_refused(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        created, _, _ = message(uow)
        with pytest.raises(IllegalTransition):
            uow.messages.transition(created.id, M.SENT, expected_version=created.row_version)
        with pytest.raises(ValueError, match="subject"):
            uow.messages.transition(
                created.id,
                M.APPROVED,
                expected_version=created.row_version,
                set_fields={"subject": "x"},
            )


def test_a_stale_message_version_is_refused(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        created, _, _ = message(uow)
        uow.messages.transition(created.id, M.APPROVED, expected_version=created.row_version)
        with pytest.raises(ConcurrencyConflict):
            uow.messages.transition(created.id, M.REJECTED, expected_version=created.row_version)


def test_a_sent_message_id_is_unique_but_unsent_ones_may_all_be_empty(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        first, _, _ = message(uow, step=0)
        second, _, _ = message(uow, step=1)  # both exist with no rfc_message_id: that is allowed
        first = uow.messages.transition(first.id, M.APPROVED, expected_version=first.row_version)
        uow.messages.transition(
            first.id,
            M.SENT,
            expected_version=first.row_version,
            set_fields={"rfc_message_id": "<same@mail>"},
        )
        second = uow.messages.transition(second.id, M.APPROVED, expected_version=second.row_version)
        with pytest.raises(IntegrityError):
            uow.messages.transition(
                second.id,
                M.SENT,
                expected_version=second.row_version,
                set_fields={"rfc_message_id": "<same@mail>"},
            )


def test_messages_can_be_listed_by_state(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        created, _, _ = message(uow)
        uow.commit()
        assert [m.id for m in uow.messages.in_state(M.GENERATED)] == [created.id]
        assert uow.messages.in_state(M.APPROVED) == []


# ------------------------------------------------------------------ suppressions


def test_suppression_stores_only_hashes_and_is_idempotent(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        assert uow.suppressions.add(
            SuppressionKind.EMAIL, "Jane@Acme.com", SuppressionReason.OPT_OUT
        )
        assert not uow.suppressions.add(
            SuppressionKind.EMAIL, " jane@acme.com", SuppressionReason.MANUAL
        )
        uow.commit()
        stored = [
            row[0] for row in uow.session.execute(text("SELECT value_hash FROM suppressions"))
        ]
        assert len(stored) == 1 and "jane" not in stored[0] and len(stored[0]) == 64
        events = uow.session.execute(
            text("SELECT data FROM events WHERE type = 'suppression_added'")
        ).all()
        assert "jane" not in str(events).lower()


def test_an_address_is_blocked_by_its_own_entry_or_its_domains(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        uow.suppressions.add(SuppressionKind.EMAIL, "jane@acme.com", SuppressionReason.OPT_OUT)
        uow.suppressions.add(SuppressionKind.DOMAIN, "beta.io", SuppressionReason.MANUAL)
        assert uow.suppressions.blocks("jane@acme.com")
        assert not uow.suppressions.blocks("sam@acme.com")
        assert uow.suppressions.blocks("anyone@beta.io")
        assert uow.suppressions.is_domain_suppressed("https://www.beta.io/about")
        assert not uow.suppressions.is_email_suppressed("anyone@beta.io")


def test_suppression_is_per_workspace(factory: UnitOfWorkFactory, ws: str, other_ws: str) -> None:
    with factory(ws) as uow:
        uow.suppressions.add(SuppressionKind.EMAIL, "jane@acme.com", SuppressionReason.OPT_OUT)
        uow.commit()
    with factory(other_ws) as uow:
        assert not uow.suppressions.blocks("jane@acme.com")


# ------------------------------------------------------------------ policies, campaigns, imports


def test_seeding_a_policy_never_overwrites_an_edited_one(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        assert uow.policies.add_if_missing(
            CountryPolicy("GB", PolicyRule.ALLOW_WITH_FOOTER, version=1)
        )
        assert not uow.policies.add_if_missing(CountryPolicy("GB", PolicyRule.BLOCK, version=9))
        stored = uow.policies.get("gb")
        assert (
            stored is not None
            and stored.rule is PolicyRule.ALLOW_WITH_FOOTER
            and stored.version == 1
        )
        assert uow.policies.get("FR") is None


def test_allowed_provenance_round_trips(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        uow.policies.add_if_missing(
            CountryPolicy(
                "CA", PolicyRule.ALLOW_WITH_FOOTER, allowed_provenance=(Provenance.OPERATOR_GIVEN,)
            )
        )
        uow.commit()
        stored = uow.policies.get("CA")
        assert stored is not None and stored.allowed_provenance == (Provenance.OPERATOR_GIVEN,)


def test_a_campaign_has_defaults_and_a_unique_name(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        campaign = uow.campaigns.create("expo", ["CTO", "VP of Sales"])
        assert campaign.min_fit_score == 60 and campaign.cadence_days == (0, 3, 8)
        assert uow.campaigns.by_name("expo") == campaign
        with pytest.raises(IntegrityError):
            uow.campaigns.create("expo", ["CEO"])


def test_an_import_batch_counts_rows_by_outcome(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        batch = uow.imports.create_batch(ImportSource.CSV, "operator", filename="expo.csv")
        uow.imports.add_row(
            batch, {"domain": "a.com"}, ImportAnchor.DOMAIN, ImportRowStatus.ACCEPTED, row_number=2
        )
        uow.imports.add_row(
            batch, {"domain": "b.com"}, ImportAnchor.DOMAIN, ImportRowStatus.MERGED, row_number=3
        )
        uow.imports.add_row(
            batch,
            {"domain": "gmail.com"},
            ImportAnchor.DOMAIN,
            ImportRowStatus.REJECTED,
            row_number=4,
            reason="free mail",
        )
        assert uow.imports.finish_batch(batch) == {
            "read": 3,
            "accepted": 1,
            "merged": 1,
            "rejected": 1,
        }
        assert uow.imports.row_statuses(batch) == [
            ImportRowStatus.ACCEPTED, ImportRowStatus.MERGED, ImportRowStatus.REJECTED,
        ]  # fmt: skip


# ------------------------------------------------------------------ runs and the call ledger


def test_a_run_totals_the_cost_of_its_calls(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        run = uow.runs.start(RunKind.PIPELINE, {"limit": 5})
        uow.calls.record(
            provider="hunter",
            operation="find_email",
            request_hash="a",
            outcome=CallOutcome.HIT,
            cost_micro_usd=24_500,
            run_id=run,
        )
        uow.calls.record(
            provider="hunter",
            operation="verify",
            request_hash="b",
            outcome=CallOutcome.HIT,
            cost_micro_usd=12_250,
            run_id=run,
        )
        uow.calls.record(
            provider="hunter",
            operation="verify",
            request_hash="b",
            outcome=CallOutcome.CACHE_HIT,
            run_id=run,
        )
        uow.runs.finish(run, RunStatus.SUCCEEDED, {"companies": 3})
        uow.commit()
        assert uow.runs.cost_of(run) == 36_750
        assert uow.runs.status(run) is RunStatus.SUCCEEDED


def test_the_cache_returns_the_newest_reusable_answer_within_the_window(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    now = utcnow()
    with factory(ws) as uow:

        def ask(outcome: CallOutcome, response: dict[str, str] | None = None) -> None:
            uow.calls.record(
                provider="hunter",
                operation="find_email",
                request_hash="h1",
                outcome=outcome,
                response=response,
            )

        ask(CallOutcome.HIT, {"email": "old@acme.com"})
        ask(CallOutcome.ERROR, {"error": "boom"})
        ask(CallOutcome.BLOCKED_BY_CAP)
        uow.commit()
        assert uow.calls.cached_response("hunter", "find_email", "h1", now - timedelta(days=1)) == {
            "email": "old@acme.com"
        }
        assert (
            uow.calls.cached_response("hunter", "find_email", "h1", now + timedelta(days=1)) is None
        )
        assert (
            uow.calls.cached_response("hunter", "find_email", "other", now - timedelta(days=1))
            is None
        )


def test_a_miss_is_reusable_so_a_repeat_costs_nothing(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        uow.calls.record(
            provider="hunter", operation="find_email", request_hash="m", outcome=CallOutcome.MISS
        )
        found = uow.calls.cached_response("hunter", "find_email", "m", utcnow() - timedelta(days=1))
        assert found == {}


def test_spend_is_totalled_by_provider_and_by_company(factory: UnitOfWorkFactory, ws: str) -> None:
    now = utcnow()
    with factory(ws) as uow:
        company = uow.companies.create(domain="acme.com", source=CompanySource.MANUAL)
        for provider_name, cost in (("hunter", 100), ("hunter", 50), ("tavily", 7)):
            uow.calls.record(
                provider=provider_name, operation="x", request_hash="r", outcome=CallOutcome.HIT,
                cost_micro_usd=cost, company_id=company.id,
            )  # fmt: skip
        uow.commit()
        since = now - timedelta(hours=1)
        assert uow.calls.spend_since("hunter", since) == 150
        assert uow.calls.spend_since("tavily", since) == 7
        assert uow.calls.spend_on_company(company.id) == 157
        assert uow.calls.spend_since("hunter", now + timedelta(hours=1)) == 0
