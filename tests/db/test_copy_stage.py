"""Stage 6 under the runner: what is saved, the footer, and the sender-profile checks."""

from __future__ import annotations

from typing import Any

from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.actors import OPERATOR
from outbound.domain.entities import Company
from outbound.domain.enums import (
    CompanySource,
    CompanyStatus,
    ContactSource,
    EmailStatus,
    MessageState,
    Provenance,
)
from outbound.domain.policy_seeds import DEFAULT_COUNTRY_POLICIES
from outbound.runner.guards import Guards
from outbound.runner.runner import Runner
from outbound.stages.copy.stage import CopyStage
from tests.stages.fakes import GOOD_SNIPPETS, ScriptedLlm

C = CompanyStatus
SPECIFIC = {"specific": True, "problem": ""}
PROFILE = {
    "reviewed_at": "2026-10-18T00:00:00+00:00",
    "company_name": "Quantra",
    "narrative": "We forecast renewable output.",
    "value_propositions": ["Cuts forecast error 20-35%"],
    "signature_name": "Sam Lee",
    "signature_title": "CPO, Quantra",
    "legal_name": "Quantra Energy Inc",
    "postal_address": "1 Main St, Austin TX",
    "registration_details": "",
    "contact_info": "",
}


def set_profile(factory: UnitOfWorkFactory, ws: str, **overrides: Any) -> None:
    from outbound.db.models import WorkspaceRow

    with factory(ws) as uow:
        row = uow.session.get(WorkspaceRow, ws)
        assert row is not None
        row.sender_profile = {**PROFILE, **overrides}
        uow.commit()


def lead(
    factory: UnitOfWorkFactory,
    ws: str,
    *,
    status: EmailStatus = EmailStatus.VALID,
    country: str = "US",
) -> str:
    with factory(ws) as uow:
        for policy in DEFAULT_COUNTRY_POLICIES:
            uow.policies.add_if_missing(policy)
        campaign = uow.campaigns.create("expo", ["CTO"])
        company = uow.companies.create(
            domain="acme.com",
            source=CompanySource.MANUAL,
            country_code=country,
            name="Acme",
            campaign_id=campaign.id,
        )
        company = uow.companies.update_fields(
            company.id,
            {"research": {"summary": "Solar fleet operator", "news": ["Leeds office"]}},
            actor="system",
            expected_version=company.row_version,
        )
        version = company.row_version
        for step in (C.RESEARCHED, C.QUALIFIED, C.CONTACTS_FOUND, C.EMAIL_READY):
            version = uow.companies.transition(
                company.id, step, expected_version=version
            ).row_version
        contact = uow.contacts.add(
            company.id,
            rank=1,
            source=ContactSource.SITE,
            full_name="Jane Doe",
            first_name="Jane",
            last_name="Doe",
            title="CTO",
        )
        uow.emails.add(
            contact.id, "jane.doe@acme.com", Provenance.API_DATABASE, status=status, is_primary=True
        )
        uow.commit()
        return company.id


def run_copy_stage(factory: UnitOfWorkFactory, ws: str, llm: ScriptedLlm, **kwargs: Any) -> None:
    Runner(factory, ws, [CopyStage(llm, **kwargs)], Guards()).run_pipeline()


def company(factory: UnitOfWorkFactory, ws: str, company_id: str) -> Company:
    with factory(ws) as uow:
        return uow.companies.get(company_id)


def test_touch_one_is_saved_as_a_generated_message_with_its_working(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    set_profile(factory, ws)
    cid = lead(factory, ws)
    run_copy_stage(factory, ws, ScriptedLlm([GOOD_SNIPPETS], [SPECIFIC]))
    assert company(factory, ws, cid).status is C.COPY_READY
    with factory(ws) as uow:
        [message] = uow.messages.for_company(cid)
    assert (message.step, message.state) == (0, MessageState.GENERATED)
    assert message.subject == "leeds solar forecasts"
    assert message.generated_body.startswith("Hi Jane,")
    assert message.snippets is not None and message.snippets["hook"].startswith("I saw that Acme")
    assert message.lint_report is not None and message.lint_report["flagged"] is False
    assert message.final_body is None


def test_the_country_footer_is_filled_from_the_sender_profile(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    set_profile(factory, ws)
    cid = lead(factory, ws)
    run_copy_stage(factory, ws, ScriptedLlm([GOOD_SNIPPETS], [SPECIFIC]))
    with factory(ws) as uow:
        [message] = uow.messages.for_company(cid)
    assert message.generated_body.endswith(
        '--\nQuantra Energy Inc, 1 Main St, Austin TX. Reply "unsubscribe" and we will stop.'
    )


def test_a_blank_sender_field_the_footer_needs_fails_the_lead_with_the_field_names(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    set_profile(factory, ws, legal_name="", postal_address="")
    cid = lead(factory, ws)
    llm = ScriptedLlm([GOOD_SNIPPETS], [SPECIFIC])
    run_copy_stage(factory, ws, llm)
    after = company(factory, ws, cid)
    assert (after.status, after.failed_stage) == (C.FAILED, "copy")
    assert "legal_name" in (after.last_error or "") and "postal_address" in (after.last_error or "")
    assert llm.calls == []  # no model money is spent on a draft that cannot be legal


def test_a_placeholder_signature_fails_the_lead(factory: UnitOfWorkFactory, ws: str) -> None:
    set_profile(factory, ws, signature_name="[Your Name]")
    cid = lead(factory, ws)
    run_copy_stage(factory, ws, ScriptedLlm([GOOD_SNIPPETS], [SPECIFIC]))
    after = company(factory, ws, cid)
    assert after.status is C.FAILED and "signature_name" in (after.last_error or "")


def test_a_lead_whose_address_is_not_safe_cannot_be_written_to(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    set_profile(factory, ws)
    cid = lead(factory, ws, status=EmailStatus.UNKNOWN)
    run_copy_stage(factory, ws, ScriptedLlm([GOOD_SNIPPETS], [SPECIFIC]))
    after = company(factory, ws, cid)
    assert after.status is C.FAILED and "safe to send" in (after.last_error or "")


def test_a_draft_that_cannot_pass_the_linter_is_still_handed_over_flagged(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    set_profile(factory, ws)
    cid = lead(factory, ws)
    short = {**GOOD_SNIPPETS, "value": "We help.", "relevance": "It matters."}
    run_copy_stage(factory, ws, ScriptedLlm([short]))
    assert company(factory, ws, cid).status is C.COPY_READY
    with factory(ws) as uow:
        [message] = uow.messages.for_company(cid)
    assert message.lint_report is not None and message.lint_report["flagged"] is True


def test_recent_operator_edits_in_the_same_campaign_become_examples(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    set_profile(factory, ws)
    first = lead(factory, ws)
    llm_first = ScriptedLlm([GOOD_SNIPPETS], [SPECIFIC])
    run_copy_stage(factory, ws, llm_first)
    assert "Earlier drafts" not in llm_first.prompts["actor"][0]

    with factory(ws) as uow:
        [message] = uow.messages.for_company(first)
        uow.messages.transition(
            message.id,
            MessageState.APPROVED,
            expected_version=message.row_version,
            actor=OPERATOR,
            set_fields={"final_body": "Hi Jane, much shorter.", "edit_distance": 0.6},
        )
        company_row = uow.companies.get(first)
        campaign_id = company_row.campaign_id
        second = uow.companies.create(
            domain="beta.com",
            source=CompanySource.MANUAL,
            country_code="US",
            name="Beta",
            campaign_id=campaign_id,
        )
        uow.commit()
    _advance_to_email_ready(factory, ws, second.id)
    llm_second = ScriptedLlm([GOOD_SNIPPETS], [SPECIFIC])
    run_copy_stage(factory, ws, llm_second)
    prompt = llm_second.prompts["actor"][0]
    assert "Hi Jane, much shorter." in prompt and "Earlier drafts" in prompt


def _advance_to_email_ready(factory: UnitOfWorkFactory, ws: str, company_id: str) -> None:
    with factory(ws) as uow:
        version = uow.companies.get(company_id).row_version
        for step in (C.RESEARCHED, C.QUALIFIED, C.CONTACTS_FOUND, C.EMAIL_READY):
            version = uow.companies.transition(
                company_id, step, expected_version=version
            ).row_version
        contact = uow.contacts.add(
            company_id, rank=1, source=ContactSource.SITE, first_name="Al", full_name="Al Beta"
        )
        uow.emails.add(
            contact.id,
            "al@beta.com",
            Provenance.API_DATABASE,
            status=EmailStatus.VALID,
            is_primary=True,
        )
        uow.commit()


def test_asking_for_zero_examples_turns_the_feature_off(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    set_profile(factory, ws)
    lead(factory, ws)
    llm = ScriptedLlm([GOOD_SNIPPETS], [SPECIFIC])
    run_copy_stage(factory, ws, llm, examples=0)
    assert "Earlier drafts" not in llm.prompts["actor"][0]


def test_nothing_is_written_until_the_operator_has_reviewed_the_profile(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    set_profile(factory, ws)
    with factory(ws) as uow:  # the profile as it is right after seeding: never reviewed
        from outbound.db.models import WorkspaceRow

        row = uow.session.get(WorkspaceRow, ws)
        assert row is not None
        row.sender_profile = {k: v for k, v in row.sender_profile.items() if k != "reviewed_at"}
        uow.commit()
    cid = lead(factory, ws)
    llm = ScriptedLlm([GOOD_SNIPPETS], [SPECIFIC])
    run_copy_stage(factory, ws, llm)
    after = company(factory, ws, cid)
    assert after.status is C.FAILED and "review and save your sender profile" in (
        after.last_error or ""
    )
    assert llm.calls == []  # not a single model call is spent on an email that cannot be sent


def test_a_lead_released_after_its_email_was_withdrawn_gets_a_fresh_first_email(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    set_profile(factory, ws)
    cid = lead(factory, ws)
    with factory(ws) as uow:  # the earlier first email was cancelled when the lead was put on hold
        contact = uow.contacts.for_company(cid)[0]
        address = uow.emails.for_contact(contact.id)[0]
        uow.messages.create(
            company_id=cid,
            contact_id=contact.id,
            contact_email_id=address.id,
            step=0,
            subject="old",
            generated_body="old",
            state=MessageState.CANCELLED,
        )
        uow.commit()
    run_copy_stage(factory, ws, ScriptedLlm([GOOD_SNIPPETS], [SPECIFIC]))
    assert company(factory, ws, cid).status is C.COPY_READY
    with factory(ws) as uow:
        states = sorted(m.state.value for m in uow.messages.for_company(cid))
    assert states == ["cancelled", "generated"]
