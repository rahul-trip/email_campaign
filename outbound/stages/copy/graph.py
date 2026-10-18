"""Copy as a small actor-critic loop in LangGraph.

    actor -> assemble -> critic -> (done | back to actor, at most twice)

The actor (a model) writes five short parts. Code assembles them into the email and appends the
footer, so length, structure and legal text never depend on a model's mood. The critic runs the
linter first; only a draft that passes is shown to a model, for one question: is the hook really
about this company? A draft that is still failing after two rewrites goes on, flagged, so the
operator sees the problem instead of the engine hiding it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict

from outbound.domain.copy_lint import LintIssue, LintReport, lint
from outbound.prompts import copy as prompts
from outbound.providers.llm_json import ask_json as ask
from outbound.providers.ports import LlmClient

MAX_REWRITES = 2


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


@dataclass(frozen=True)
class CopyOutput:
    subject: str
    body: str
    snippets: dict[str, str]
    report: LintReport
    attempts: int


class Snippets(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hook: str
    relevance: str
    value: str
    ask: str
    subject: str


class _Specificity(BaseModel):
    model_config = ConfigDict(extra="ignore")

    specific: bool = True
    problem: str = ""


def assemble_email(inp: CopyInput, snippets: Snippets) -> str:
    """Greeting, three short paragraphs, sign-off, then the footer."""
    sender = inp.sender
    opening = f"{snippets.hook.strip()} {snippets.relevance.strip()}"
    signature = "\n".join(
        part
        for part in (str(sender.get("signature_name", "")), str(sender.get("signature_title", "")))
        if part
    )
    body = (
        f"Hi {inp.first_name},\n\n{opening}\n\n{snippets.value.strip()}\n\n"
        f"{snippets.ask.strip()}\n\n{signature}"
    )
    return f"{body}\n\n--\n{inp.footer}" if inp.footer else body


class CopyState(TypedDict, total=False):
    attempt: int
    snippets: Snippets
    body: str
    report: LintReport
    feedback: str
    passed: bool
    problem: str


def build_copy_graph(llm: LlmClient, inp: CopyInput):  # type: ignore[no-untyped-def]
    def actor(state: CopyState) -> CopyState:
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
        )
        written = ask(llm, prompts.ACTOR_SYSTEM_PROMPT, user, Snippets)
        return {"attempt": state.get("attempt", 0) + 1, "snippets": written}

    def assemble(state: CopyState) -> CopyState:
        return {"body": assemble_email(inp, state["snippets"])}

    def critic(state: CopyState) -> CopyState:
        snippets = state["snippets"]
        report = lint(body=state["body"], subject=snippets.subject, step=0, footer=inp.footer)
        if report.flagged:
            return {"report": report, "feedback": report.feedback(), "passed": False, "problem": ""}
        verdict = ask(
            llm,
            prompts.CRITIC_SYSTEM_PROMPT,
            prompts.build_critic_user_prompt(inp.company_name, inp.research, snippets.hook),
            _Specificity,
        )
        if verdict.specific:
            return {"report": report, "feedback": "", "passed": True, "problem": ""}
        problem = verdict.problem or "The opening hook is generic; name something specific."
        return {"report": report, "feedback": f"- {problem}", "passed": False, "problem": problem}

    def route(state: CopyState) -> Literal["actor", "__end__"]:
        if state["passed"] or state["attempt"] > MAX_REWRITES:
            return "__end__"
        return "actor"

    graph: StateGraph = StateGraph(CopyState)
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
    snippets = state["snippets"]
    report = state["report"]
    if state.get("problem"):  # the lint passed, but the critic found the hook generic
        report = LintReport(
            (*report.issues, LintIssue("specificity", state["problem"])),
            report.word_count,
            report.reading_grade,
        )
    return CopyOutput(
        subject=snippets.subject.strip(),
        body=state["body"],
        snippets=snippets.model_dump(),
        report=report,
        attempts=state["attempt"],
    )
