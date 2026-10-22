"""Copy as a small actor-critic loop in LangGraph.

    actor -> assemble -> critic -> (done | back to actor, at most twice)

The actor (a model) writes the paragraphs of the email and says which news item it opened with.
Code adds the greeting, signature and footer, so the legal text and the sign-off never depend on
a model's mood. The critic checks cheap, certain things first (the linter, and that the source is
one the research really found); only a draft that passes is shown to a model, for the two
questions code cannot answer: is every fact supported, and does it read like a person wrote it?
A draft still failing after two rewrites goes on, flagged, so the operator sees the problem
instead of the engine hiding it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, field_validator

from outbound.domain.copy_lint import LintIssue, LintReport, LintRules, lint
from outbound.prompts import copy as prompts
from outbound.providers.llm_json import ask_json as ask
from outbound.providers.ports import LlmClient

MAX_REWRITES = 2
GREETINGS = ("Hi", "Hello", "Dear")


@dataclass(frozen=True)
class CopyInput:
    sender: dict[str, Any]
    first_name: str
    title: str
    company_name: str
    research: dict[str, Any] = field(default_factory=dict)
    answers: dict[str, str] = field(default_factory=dict)
    notes: str = ""
    examples: tuple[tuple[str, str], ...] = ()
    footer: str | None = None
    rules: LintRules = field(default_factory=LintRules)


@dataclass(frozen=True)
class CopyOutput:
    subject: str
    body: str
    snippets: dict[str, Any]
    report: LintReport
    attempts: int


class Draft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    subject: str
    body: str
    based_on: str = ""

    @field_validator("subject")
    @classmethod
    def _one_line(cls, value: str) -> str:
        """A subject is a single line: newlines would make delivery fail, or inject headers."""
        return " ".join(value.split())

    @field_validator("body")
    @classmethod
    def _paragraphs(cls, value: str) -> str:
        """Single blank lines between paragraphs, and nothing before or after them."""
        return re.sub(r"\n{3,}", "\n\n", value.replace("\r\n", "\n")).strip()


class _Verdict(BaseModel):
    model_config = ConfigDict(extra="ignore")

    grounded: bool = True
    human: bool = True
    problem: str = ""


def greeting_for(sender: dict[str, Any]) -> str:
    chosen = str(sender.get("greeting") or "").strip()
    return chosen if chosen in GREETINGS else GREETINGS[0]


def assemble_email(inp: CopyInput, draft: Draft) -> str:
    """Greeting, the writer's paragraphs, sign-off, then the footer."""
    sender = inp.sender
    signature = "\n".join(
        part
        for part in (str(sender.get("signature_name", "")), str(sender.get("signature_title", "")))
        if part
    )
    body = f"{greeting_for(sender)} {inp.first_name},\n\n{draft.body}\n\n{signature}"
    return f"{body}\n\n--\n{inp.footer}" if inp.footer else body


def news_sources(research: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every dated item research found, by url: what an email may say it opened with."""
    found: dict[str, dict[str, Any]] = {}
    for key in ("news_items", "triggers"):
        for item in research.get(key) or []:
            if isinstance(item, dict) and item.get("url"):
                found[str(item["url"])] = item
    return found


def source_issues(draft: Draft, research: dict[str, Any]) -> list[LintIssue]:
    """The writer's claim about what it opened with, checked against what research found."""
    sources = news_sources(research)
    based_on = draft.based_on.strip()
    if based_on and based_on not in sources:
        return [
            LintIssue(
                "source",
                "based_on is not one of the urls in the research notes. Copy a url exactly, or"
                " leave it empty if you opened with a fact from their site.",
            )
        ]
    if sources and not based_on:
        first = next(iter(sources.values()))
        return [
            LintIssue(
                "opening",
                "The research found recent news, but the email does not open with it. Open with:"
                f" {first.get('headline', '')} (url: {first.get('url', '')}).",
            )
        ]
    return []


class CopyState(TypedDict, total=False):
    attempt: int
    draft: Draft
    body: str
    report: LintReport
    feedback: str
    passed: bool
    problem: str
    problem_rule: str


def build_copy_graph(llm: LlmClient, inp: CopyInput):  # type: ignore[no-untyped-def]
    low, high = inp.rules.first_touch_words

    def actor(state: CopyState) -> CopyState:
        previous = state.get("draft")
        user = prompts.build_actor_user_prompt(
            sender=inp.sender,
            recipient=inp.first_name,
            title=inp.title,
            company=inp.company_name,
            research=inp.research,
            answers=inp.answers,
            notes=inp.notes,
            examples=inp.examples,
            feedback=state.get("feedback", ""),
            previous=previous.body if previous else "",
        )
        written = ask(llm, prompts.actor_system_prompt(low, high), user, Draft)
        return {"attempt": state.get("attempt", 0) + 1, "draft": written}

    def assemble(state: CopyState) -> CopyState:
        return {"body": assemble_email(inp, state["draft"])}

    def critic(state: CopyState) -> CopyState:
        draft = state["draft"]
        report = lint(
            body=state["body"],
            subject=draft.subject,
            step=0,
            footer=inp.footer,
            core=draft.body,
            rules=inp.rules,
        )
        extra = source_issues(draft, inp.research)
        if extra:
            report = LintReport((*report.issues, *extra), report.word_count, report.reading_grade)
        if report.flagged:
            return {
                "report": report,
                "feedback": report.feedback(),
                "passed": False,
                "problem": "",
            }
        verdict = ask(
            llm,
            prompts.CRITIC_SYSTEM_PROMPT,
            prompts.build_critic_user_prompt(
                inp.company_name, inp.sender, inp.research, draft.body
            ),
            _Verdict,
        )
        if verdict.grounded and verdict.human:
            return {"report": report, "feedback": "", "passed": True, "problem": ""}
        problem = verdict.problem or (
            "A fact is not in the research notes." if not verdict.grounded else "It reads as AI."
        )
        return {
            "report": report,
            "feedback": f"- {problem}",
            "passed": False,
            "problem": problem,
            "problem_rule": "grounded" if not verdict.grounded else "human",
        }

    def route(state: CopyState) -> Literal["actor", "__end__"]:
        if state["passed"] or state["attempt"] > MAX_REWRITES:
            return "__end__"
        return "actor"

    graph = StateGraph(CopyState)
    graph.add_node("actor", actor)
    graph.add_node("assemble", assemble)
    graph.add_node("critic", critic)
    graph.add_edge(START, "actor")
    graph.add_edge("actor", "assemble")
    graph.add_edge("assemble", "critic")
    graph.add_conditional_edges("critic", route, {"actor": "actor", "__end__": END})
    return graph.compile()


def run_copy(llm: LlmClient, inp: CopyInput) -> CopyOutput:
    state: CopyState = build_copy_graph(llm, inp).invoke({"attempt": 0})
    draft = state["draft"]
    report = state["report"]
    if state.get("problem"):  # the lint passed, but the critic found a fact or the voice wrong
        report = LintReport(
            (*report.issues, LintIssue(state.get("problem_rule", "human"), state["problem"])),
            report.word_count,
            report.reading_grade,
        )
    opening = news_sources(inp.research).get(draft.based_on.strip())
    return CopyOutput(
        subject=draft.subject.strip(),
        body=state["body"],
        snippets={
            "subject": draft.subject.strip(),
            "based_on": draft.based_on.strip(),
            "opening": opening,
        },
        report=report,
        attempts=state["attempt"],
    )


# ------------------------------------------------------------------ the operator's revisions

FOOTER_MARK = "\n\n--\n"


class _Revision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    body: str

    @field_validator("body")
    @classmethod
    def _tidy(cls, value: str) -> str:
        return re.sub(r"\n{3,}", "\n\n", value.replace("\r\n", "\n")).strip()


@dataclass(frozen=True)
class Revision:
    body: str  # the whole email again, footer included exactly as it was
    report: LintReport


def revise_email(
    llm: LlmClient,
    *,
    email: str,
    instructions: str,
    sender: dict[str, Any],
    research: dict[str, Any],
    subject: str,
    rules: LintRules,
) -> Revision:
    """Rewrite an email the way the operator asks; the legal footer is put back untouched.

    The operator's instructions win over the usual style rules, so the result is checked (and the
    report shown) but never rewritten again by the engine.
    """
    main, mark, footer = email.partition(FOOTER_MARK)
    revised = ask(
        llm,
        prompts.REVISE_SYSTEM_PROMPT,
        prompts.build_revise_user_prompt(
            email=main, instructions=instructions, research=research, sender=sender
        ),
        _Revision,
    )
    body = f"{revised.body}{mark}{footer}" if mark else revised.body
    report = lint(body=body, subject=subject, step=0, footer=footer.strip() or None, rules=rules)
    return Revision(body, report)
