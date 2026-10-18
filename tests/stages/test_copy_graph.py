"""Copy: assembly, the rewrite loop and its stopping rule, with a scripted model."""

from __future__ import annotations

from typing import Any

import pytest

from outbound.providers.errors import ProviderError
from outbound.stages.copy.graph import MAX_REWRITES, CopyInput, Snippets, assemble_email, run_copy
from tests.stages.fakes import GOOD_SNIPPETS, ScriptedLlm

FOOTER = "Quantra Ltd, 1 High St, Leeds. Reply unsubscribe and we will stop."
SENDER = {
    "company_name": "Quantra",
    "narrative": "We forecast renewable output.",
    "value_propositions": ["Cuts forecast error 20-35%"],
    "signature_name": "Sam Lee",
    "signature_title": "CPO, Quantra",
}
SPECIFIC = {"specific": True, "problem": ""}
GENERIC = {"specific": False, "problem": "Name the Leeds office, not the industry."}


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


def too_short(**changes: str) -> dict[str, str]:
    return {**GOOD_SNIPPETS, "value": "We help.", "relevance": "It matters.", **changes}


def test_the_email_is_assembled_by_code_with_greeting_signature_and_footer() -> None:
    body = assemble_email(inp(), Snippets(**GOOD_SNIPPETS))
    assert body.startswith("Hi Jane,\n\nI saw that Acme opened")
    assert body.index("Would a short call") < body.index("Sam Lee\nCPO, Quantra")
    assert body.endswith(f"\n\n--\n{FOOTER}")


def test_no_footer_means_none_is_added() -> None:
    assert "--" not in assemble_email(inp(footer=None), Snippets(**GOOD_SNIPPETS))


def test_a_good_first_draft_costs_one_writer_call_and_one_check() -> None:
    llm = ScriptedLlm([GOOD_SNIPPETS], [SPECIFIC])
    out = run_copy(llm, inp())
    assert llm.calls == ["actor", "critic"]
    assert not out.report.flagged, out.report.feedback()
    assert (out.subject, out.attempts) == ("leeds solar forecasts", 1)
    assert out.snippets["ask"] == "Would a short call next week make sense?"
    assert 50 <= out.report.word_count <= 85


def test_a_draft_that_breaks_the_rules_is_rewritten_with_the_reasons() -> None:
    llm = ScriptedLlm([too_short(), GOOD_SNIPPETS], [SPECIFIC])
    out = run_copy(llm, inp())
    assert out.attempts == 2 and not out.report.flagged
    assert "must be 50 to 85 words" in llm.prompts["actor"][1]
    assert "Fix these problems" not in llm.prompts["actor"][0]
    assert llm.calls == ["actor", "actor", "critic"]  # the model is not asked about a failing draft


def test_a_draft_that_never_passes_stops_after_two_rewrites_and_is_flagged() -> None:
    llm = ScriptedLlm([too_short()])
    out = run_copy(llm, inp())
    assert out.attempts == MAX_REWRITES + 1 == 3
    assert llm.calls == ["actor"] * 3
    assert out.report.flagged
    assert "length" in {i.rule for i in out.report.issues}


def test_a_generic_hook_is_sent_back_and_the_problem_reaches_the_writer() -> None:
    llm = ScriptedLlm([GOOD_SNIPPETS, GOOD_SNIPPETS], [GENERIC, SPECIFIC])
    out = run_copy(llm, inp())
    assert out.attempts == 2 and not out.report.flagged
    assert "Name the Leeds office" in llm.prompts["actor"][1]


def test_a_hook_that_stays_generic_is_flagged_for_the_operator() -> None:
    llm = ScriptedLlm([GOOD_SNIPPETS], [GENERIC])
    out = run_copy(llm, inp())
    assert out.attempts == 3
    assert [i.rule for i in out.report.issues] == ["specificity"]
    assert "Leeds office" in out.report.issues[0].message


def test_a_banned_phrase_is_caught_without_asking_a_model() -> None:
    dirty = {**GOOD_SNIPPETS, "hook": "I hope this email finds you well, Acme opened Leeds."}
    llm = ScriptedLlm([dirty, GOOD_SNIPPETS], [SPECIFIC])
    out = run_copy(llm, inp())
    assert "banned_phrase" not in {i.rule for i in out.report.issues}
    assert "Remove the phrase 'i hope this email finds you well'" in llm.prompts["actor"][1]


def test_operator_edits_are_shown_to_the_writer_as_before_and_after() -> None:
    llm = ScriptedLlm([GOOD_SNIPPETS], [SPECIFIC])
    run_copy(llm, inp(examples=(("generated text A", "sent text B"),)))
    prompt = llm.prompts["actor"][0]
    assert "generated text A" in prompt and "sent text B" in prompt
    assert "Earlier drafts the operator corrected" in prompt


def test_research_notes_and_operator_notes_reach_the_writer() -> None:
    llm = ScriptedLlm([GOOD_SNIPPETS], [SPECIFIC])
    run_copy(llm, inp(notes="met at the expo", answers={"Do they trade?": "Yes"}))
    prompt = llm.prompts["actor"][0]
    assert (
        "Leeds office" in prompt and "met at the expo" in prompt and "Do they trade?: Yes" in prompt
    )


def test_only_facts_from_the_sender_profile_are_offered_as_proof() -> None:
    llm = ScriptedLlm([GOOD_SNIPPETS], [SPECIFIC])
    run_copy(llm, inp())
    assert "Cuts forecast error 20-35%" in llm.prompts["actor"][0]


@pytest.mark.parametrize("reply", ["not json", {"hook": "only a hook"}])
def test_a_reply_that_cannot_be_used_is_a_provider_error(reply: Any) -> None:
    with pytest.raises(ProviderError):
        run_copy(ScriptedLlm([reply]), inp())
