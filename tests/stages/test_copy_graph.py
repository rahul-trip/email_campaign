"""Copy: assembly, source checks, the rewrite loop and its stopping rule, with a scripted model."""

from __future__ import annotations

from typing import Any

import pytest

from outbound.domain.copy_lint import LintRules
from outbound.providers.errors import ProviderError
from outbound.stages.copy.graph import MAX_REWRITES, CopyInput, Draft, assemble_email, run_copy
from tests.stages.fakes import GOOD_BODY, GOOD_DRAFT, ScriptedLlm

FOOTER = "Quantra Ltd, 1 High St, Leeds. Reply unsubscribe and we will stop."
SENDER = {
    "company_name": "Quantra",
    "narrative": "We forecast renewable output.",
    "value_propositions": ["Cuts forecast error 20-35%"],
    "signature_name": "Sam Lee",
    "signature_title": "CPO, Quantra",
}
FINE = {"grounded": True, "human": True, "problem": ""}
INVENTED = {"grounded": False, "human": True, "problem": "Acme has no Leeds office in the notes."}
STIFF = {"grounded": True, "human": False, "problem": "Rewrite 'a lot bigger' in plain words."}
NEWS = {
    "date": "2026-10-10",
    "headline": "Acme wins Leeds grid contract",
    "detail": "A three-year deal.",
    "matters": "",
    "url": "https://news.example.com/acme",
}


def inp(**kwargs: Any) -> CopyInput:
    values: dict[str, Any] = {
        "sender": SENDER,
        "first_name": "Jane",
        "title": "CTO",
        "company_name": "Acme",
        "research": {"summary": "Solar fleet operator", "news": ["Leeds office"]},
        "footer": FOOTER,
    }
    values.update(kwargs)
    return CopyInput(**values)


def too_short() -> dict[str, str]:
    return {**GOOD_DRAFT, "body": "Short. Would a call help?"}


def with_news(**changes: Any) -> dict[str, Any]:
    return {"summary": "Solar fleet operator", "news_items": [NEWS], "triggers": [], **changes}


# ------------------------------------------------------------------ assembly


def test_the_email_is_assembled_by_code_with_greeting_signature_and_footer() -> None:
    body = assemble_email(inp(), Draft(**GOOD_DRAFT))
    assert body.startswith("Hi Jane,\n\nAcme's Leeds office opened")
    assert body.index("short call?") < body.index("Sam Lee\nCPO, Quantra")
    assert body.endswith(f"\n\n--\n{FOOTER}")


@pytest.mark.parametrize(
    ("choice", "shown"), [("Dear", "Dear"), ("Hello", "Hello"), ("Yo", "Hi"), ("", "Hi")]
)
def test_the_greeting_is_the_operators_choice_from_a_short_list(choice: str, shown: str) -> None:
    body = assemble_email(inp(sender={**SENDER, "greeting": choice}), Draft(**GOOD_DRAFT))
    assert body.startswith(f"{shown} Jane,")


def test_no_footer_means_none_is_added() -> None:
    assert "--" not in assemble_email(inp(footer=None), Draft(**GOOD_DRAFT))


def test_paragraph_breaks_are_tidied() -> None:
    draft = Draft(subject="a\nb", body="\n\nOne.\n\n\n\n\nTwo?\n", based_on="")
    assert (draft.subject, draft.body) == ("a b", "One.\n\nTwo?")


# ------------------------------------------------------------------ the loop


def test_a_good_first_draft_costs_one_writer_call_and_one_check() -> None:
    llm = ScriptedLlm([GOOD_DRAFT], [FINE])
    out = run_copy(llm, inp())
    assert llm.calls == ["actor", "critic"]
    assert not out.report.flagged, out.report.feedback()
    assert (out.subject, out.attempts) == ("leeds solar forecasts", 1)
    assert 120 <= out.report.word_count <= 200
    assert out.snippets == {"subject": "leeds solar forecasts", "based_on": "", "opening": None}


def test_the_length_comes_from_the_rules() -> None:
    llm = ScriptedLlm([GOOD_DRAFT])
    out = run_copy(llm, inp(rules=LintRules.with_length(300, 400)))
    assert "300 to 400 words" in llm.systems["actor"][0]  # the writer is told the length
    assert "length" in {i.rule for i in out.report.issues}


def test_a_draft_that_breaks_the_rules_is_rewritten_with_the_reasons_and_its_last_text() -> None:
    llm = ScriptedLlm([too_short(), GOOD_DRAFT], [FINE])
    out = run_copy(llm, inp())
    assert out.attempts == 2 and not out.report.flagged
    assert "must be 120 to 200 words" in llm.prompts["actor"][1]
    assert "Short. Would a call help?" in llm.prompts["actor"][1]  # the rewrite sees its draft
    assert "Fix these problems" not in llm.prompts["actor"][0]
    assert llm.calls == ["actor", "actor", "critic"]  # the model is not asked about a failing draft


def test_a_draft_that_never_passes_stops_after_two_rewrites_and_is_flagged() -> None:
    llm = ScriptedLlm([too_short()])
    out = run_copy(llm, inp())
    assert out.attempts == MAX_REWRITES + 1 == 3
    assert llm.calls == ["actor"] * 3
    assert out.report.flagged
    assert "length" in {i.rule for i in out.report.issues}


def test_a_fact_that_is_not_in_the_notes_is_sent_back_with_the_problem() -> None:
    llm = ScriptedLlm([GOOD_DRAFT, GOOD_DRAFT], [INVENTED, FINE])
    out = run_copy(llm, inp())
    assert out.attempts == 2 and not out.report.flagged
    assert "no Leeds office" in llm.prompts["actor"][1]


def test_a_draft_that_stays_wrong_is_flagged_for_the_operator() -> None:
    out = run_copy(ScriptedLlm([GOOD_DRAFT], [INVENTED]), inp())
    assert out.attempts == 3
    assert [i.rule for i in out.report.issues] == ["grounded"]
    out = run_copy(ScriptedLlm([GOOD_DRAFT], [STIFF]), inp())
    assert [i.rule for i in out.report.issues] == ["human"]


# ------------------------------------------------------------------ voice and style, no model


def bad_body(sentence: str) -> dict[str, str]:
    return {**GOOD_DRAFT, "body": GOOD_BODY.replace("We work on exactly that.", sentence)}


@pytest.mark.parametrize(
    ("sentence", "told"),
    [
        (
            "I hope this email finds you well.",
            "Remove the phrase 'i hope this email finds you well'",
        ),
        ("We see strong potential for synergies here.", "Remove the phrase 'strong potential'"),
        ("Key areas:\n\n- Forecasting\n- Dispatch\n\nWe work on that.", "not a list"),
        ("We work on exactly that \u2014 really \u2014 and more \u2014 daily.", "em dash"),
    ],
)
def test_a_machine_sounding_draft_is_caught_without_asking_a_model(
    sentence: str, told: str
) -> None:
    llm = ScriptedLlm([bad_body(sentence), GOOD_DRAFT], [FINE])
    out = run_copy(llm, inp())
    assert llm.calls == ["actor", "actor", "critic"]  # no model was asked about the bad draft
    assert out.attempts == 2 and not out.report.flagged
    assert told in llm.prompts["actor"][1]


# ------------------------------------------------------------------ news as the opening


def test_with_recent_news_the_email_must_open_with_a_source_that_exists() -> None:
    llm = ScriptedLlm([GOOD_DRAFT, {**GOOD_DRAFT, "based_on": NEWS["url"]}], [FINE])
    out = run_copy(llm, inp(research=with_news()))
    assert out.attempts == 2 and not out.report.flagged
    assert "Open with: Acme wins Leeds grid contract" in llm.prompts["actor"][1]
    assert out.snippets["based_on"] == NEWS["url"]
    assert out.snippets["opening"] == NEWS  # the screens show what the email opened with


def test_a_made_up_source_url_is_rejected() -> None:
    llm = ScriptedLlm(
        [{**GOOD_DRAFT, "based_on": "https://invented.example/x"}, GOOD_DRAFT], [FINE]
    )
    out = run_copy(llm, inp())
    assert out.attempts == 2
    assert "not one of the urls" in llm.prompts["actor"][1]


def test_without_news_the_site_fact_is_fine_and_nothing_is_forced() -> None:
    out = run_copy(ScriptedLlm([GOOD_DRAFT], [FINE]), inp())
    assert out.attempts == 1 and out.snippets["opening"] is None


# ------------------------------------------------------------------ what the writer is given


def test_news_with_dates_and_links_reaches_the_writer() -> None:
    llm = ScriptedLlm([{**GOOD_DRAFT, "based_on": NEWS["url"]}], [FINE])
    run_copy(llm, inp(research=with_news()))
    prompt = llm.prompts["actor"][0]
    assert "[2026-10-10] Acme wins Leeds grid contract" in prompt and NEWS["url"] in prompt


def test_the_operators_past_emails_are_given_as_reference_not_template() -> None:
    sender = {**SENDER, "style_examples": ["Dear Knutt, we provide AI-driven forecasting."]}
    llm = ScriptedLlm([GOOD_DRAFT], [FINE])
    run_copy(llm, inp(sender=sender))
    prompt = llm.prompts["actor"][0]
    assert "Dear Knutt, we provide AI-driven forecasting." in prompt
    assert "do NOT copy their wording" in prompt


def test_the_goal_of_the_emails_reaches_the_writer() -> None:
    llm = ScriptedLlm([GOOD_DRAFT], [FINE])
    run_copy(llm, inp(sender={**SENDER, "outreach_goal": "explore a partnership"}))
    assert "explore a partnership" in llm.prompts["actor"][0]


def test_operator_edits_are_shown_to_the_writer_as_before_and_after() -> None:
    llm = ScriptedLlm([GOOD_DRAFT], [FINE])
    run_copy(llm, inp(examples=(("generated text A", "sent text B"),)))
    prompt = llm.prompts["actor"][0]
    assert "generated text A" in prompt and "sent text B" in prompt
    assert "Earlier drafts the operator corrected" in prompt


def test_research_notes_and_operator_notes_reach_the_writer() -> None:
    llm = ScriptedLlm([GOOD_DRAFT], [FINE])
    run_copy(llm, inp(notes="met at the expo", answers={"Do they trade?": "Yes"}))
    prompt = llm.prompts["actor"][0]
    assert (
        "Leeds office" in prompt and "met at the expo" in prompt and "Do they trade?: Yes" in prompt
    )


def test_only_facts_from_the_sender_profile_are_offered_as_proof() -> None:
    llm = ScriptedLlm([GOOD_DRAFT], [FINE])
    run_copy(llm, inp())
    assert "Cuts forecast error 20-35%" in llm.prompts["actor"][0]


@pytest.mark.parametrize("reply", ["not json", {"subject": "only a subject"}])
def test_a_reply_that_cannot_be_used_is_a_provider_error(reply: Any) -> None:
    with pytest.raises(ProviderError):
        run_copy(ScriptedLlm([reply]), inp())
