"""Research as a small LangGraph: fetch pages, let a supervisor pick workers, then score fit.

The graph is used as a stateless function: it takes what is known about one company and returns
what research found, with no checkpointer and no database access. Everything it spends goes
through the metered providers handed in, so each search and model call is cached, capped and
costed like any other.

    pages -> site -> (supervisor picks) -> legal | signals | persona -> fit

The site worker runs first because it reads the company's own name, and the later workers
search with it: a discovered lead arrives with no name, and a search made with a page title
instead finds the wrong people.

The supervisor is plain code (``plan_workers``) so its routing rules are unit-tested.
"""

from __future__ import annotations

import re
from collections.abc import Hashable, Sequence
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field, field_validator

from outbound.domain.enums import LegalEntityType
from outbound.domain.names import (
    clean_person_name,
    employer_matches,
    mentions_company,
    read_profile_title,
)
from outbound.logging import get_logger
from outbound.prompts import research as prompts
from outbound.providers.llm_json import ask_json as ask
from outbound.providers.ports import CompanyRegistry, LlmClient, SearchProvider
from outbound.stages.research.facts import (
    CountryInference,
    best_registry_match,
    classify_legal_entity,
    find_incorporation_markers,
    infer_country,
)

log = get_logger(__name__)

PAGE_PATHS = ("", "/about", "/team", "/news", "/contact")  # five URLs = one extract credit
PAGE_CHARS = 6_000
TOTAL_CHARS = 18_000
TEAM_HINTS = ("team", "leadership", "people", "about", "management")
MAX_PEOPLE = 5
EXTRACTION_TEMPERATURE = 0.2  # reading facts out of text, not writing: no flourishes
MIN_TEAM_TEXT = 100  # less than this is a menu, not a team page


# --------------------------------------------------------------------------- input and output


@dataclass(frozen=True)
class ResearchInput:
    domain: str
    company_name: str
    country_code: str | None = None
    notes: str = ""
    icp: str = ""
    questions: tuple[str, ...] = ()
    target_titles: tuple[str, ...] = ()
    has_operator_contact: bool = False


@dataclass(frozen=True)
class Person:
    name: str
    title: str = ""
    linkedin_url: str | None = None
    source: str = "site"  # "site" or "search"
    # False when a search found the person but their employer did not clearly match the company.
    confirmed: bool = True


@dataclass(frozen=True)
class ResearchOutput:
    research: dict[str, Any]
    answers: dict[str, str]
    country_code: str | None
    legal_entity_type: LegalEntityType
    fit_score: int | None
    fit_reason: str | None
    people: tuple[Person, ...] = field(default=())
    company_name: str | None = None  # as the company's own pages call it


# --------------------------------------------------------------------------- what a model returns


class _Reply(BaseModel):
    model_config = ConfigDict(extra="ignore")


class SiteFacts(_Reply):
    company_name: str = ""
    summary: str = ""
    products: list[str] = Field(default_factory=list)
    news: list[str] = Field(default_factory=list)
    hooks: list[str] = Field(default_factory=list)


class SignalFacts(_Reply):
    answers: dict[str, str] = Field(default_factory=dict)
    hiring: str = ""
    tech: list[str] = Field(default_factory=list)


class _TeamMember(_Reply):
    name: str = ""
    title: str = ""
    linkedin_url: str = ""


class TeamFacts(_Reply):
    people: list[_TeamMember] = Field(default_factory=list)


class FitFacts(_Reply):
    score: int = Field(ge=0, le=100)
    reason: str = ""

    @field_validator("score", mode="before")
    @classmethod
    def _clamp(cls, value: object) -> object:
        if isinstance(value, (int, float)):
            return max(0, min(100, round(value)))
        return value


# --------------------------------------------------------------------------- the supervisor

SITE, LEGAL, SIGNALS, PERSONA = "site", "legal", "signals", "persona"


def plan_workers(inp: ResearchInput) -> list[str]:
    """Which workers run for this company. Deterministic, so every rule has a test."""
    workers = [SITE]
    if inp.country_code in (None, "GB"):
        workers.append(LEGAL)
    if inp.questions:
        workers.append(SIGNALS)
    if not inp.has_operator_contact:
        workers.append(PERSONA)
    return workers


# --------------------------------------------------------------------------- state and helpers


class ResearchState(TypedDict, total=False):
    inp: ResearchInput
    page_text: dict[str, str]
    thin: bool
    site_facts: SiteFacts
    country_facts: tuple[str | None, str]
    country_suggestion: tuple[str, str]
    legal_facts: tuple[LegalEntityType, str]
    signal_facts: SignalFacts
    people_found: list[Person]
    fit_facts: FitFacts | None


def _joined(pages: dict[str, str], *, only: Sequence[str] = ()) -> str:
    parts: list[str] = []
    used = 0
    for url, text in pages.items():
        if only and not any(hint in url.lower() for hint in only):
            continue
        chunk = text.strip()[:PAGE_CHARS]
        if used + len(chunk) > TOTAL_CHARS:
            chunk = chunk[: max(0, TOTAL_CHARS - used)]
        if chunk:
            parts.append(f"[{url}]\n{chunk}")
            used += len(chunk)
    return "\n\n".join(parts)


_ADDRESS = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")


def published_addresses(pages: dict[str, str], domain: str) -> list[str]:
    """Addresses at the company's own domain that appear in the page text."""
    found: list[str] = []
    for text in pages.values():
        for match in _ADDRESS.finditer(text):
            address = match.group(0).lower()
            host = match.group(1).lower()
            own = host == domain or host.endswith("." + domain)  # not "notacme.com" for "acme.com"
            if own and address not in found:
                found.append(address)
    return found[:10]


def _clean_name(name: str) -> str:
    return clean_person_name(name)


def _company(state: ResearchState) -> str:
    """The name to search with: the one the site gave, else what was known before."""
    site = state.get("site_facts")
    return (site.company_name.strip() if site else "") or state["inp"].company_name


@dataclass(frozen=True)
class ResearchDeps:
    search: SearchProvider
    llm: LlmClient
    registry: CompanyRegistry | None = None


# --------------------------------------------------------------------------- the graph


def build_research_graph(deps: ResearchDeps):  # type: ignore[no-untyped-def]
    """Compile the graph. Returns a LangGraph runnable taking ``{"inp": ResearchInput}``."""

    def pages_node(state: ResearchState) -> ResearchState:
        inp = state["inp"]
        urls = [f"https://{inp.domain}{path}" for path in PAGE_PATHS]
        found = {page.url: page.text for page in deps.search.extract(urls) if page.text.strip()}
        if found:
            return {"page_text": found, "thin": False}
        # The site could not be read: fall back to what a search says about the company.
        hits = deps.search.search(f"{inp.company_name} {inp.domain}", max_results=5)
        snippets = {hit.url: f"{hit.title}. {hit.snippet}" for hit in hits if hit.snippet}
        return {"page_text": snippets, "thin": True}

    def supervisor(state: ResearchState) -> list[Hashable]:
        later = [w for w in plan_workers(state["inp"]) if w != SITE]
        return list[Hashable](later or ["fit"])

    def site_node(state: ResearchState) -> ResearchState:
        inp = state["inp"]
        user = prompts.build_site_user_prompt(
            inp.company_name, inp.domain, _joined(state["page_text"])
        )
        return {
            "site_facts": ask(
                deps.llm,
                prompts.SITE_SYSTEM_PROMPT,
                user,
                SiteFacts,
                temperature=EXTRACTION_TEMPERATURE,
            )
        }

    def legal_node(state: ResearchState) -> ResearchState:
        inp = state["inp"]
        text = _joined(state["page_text"])
        if inp.country_code:
            known = CountryInference(inp.country_code, "given by the operator", strong=True)
        else:
            known = infer_country(inp.domain, text)
        update: ResearchState = {
            "country_facts": (known.code if known.strong else None, known.evidence)
        }
        if not known.strong and known.code:
            update["country_suggestion"] = (known.code, known.evidence)
        entity: tuple[LegalEntityType, str] = (LegalEntityType.UNKNOWN, "not checked")
        if known.code == "GB":  # also for a suggestion, so confirming it needs no second hold
            match = None
            name = _company(state)
            if deps.registry is not None:
                entries = deps.registry.search(name)
                match = best_registry_match(name, entries)
            markers = find_incorporation_markers(text, name, inp.domain)
            entity = classify_legal_entity(markers, match)
        update["legal_facts"] = entity
        return update

    def signals_node(state: ResearchState) -> ResearchState:
        inp = state["inp"]
        name = _company(state)
        hits = deps.search.search(f"{name} {inp.domain} careers hiring technology", max_results=5)
        snippets = "\n".join(f"- {h.title}: {h.snippet}" for h in hits)
        user = prompts.build_signals_user_prompt(
            name, inp.questions, _joined(state["page_text"]), snippets
        )
        return {
            "signal_facts": ask(
                deps.llm,
                prompts.SIGNALS_SYSTEM_PROMPT,
                user,
                SignalFacts,
                temperature=EXTRACTION_TEMPERATURE,
            )
        }

    def persona_node(state: ResearchState) -> ResearchState:
        inp = state["inp"]
        name = _company(state)
        people: list[Person] = []
        # When the site could not be read the text is other sites' snippets: their people are
        # not this company's, so only the public search below is used.
        team_text = "" if state.get("thin") else _joined(state["page_text"], only=TEAM_HINTS)
        if len(team_text) > MIN_TEAM_TEXT:
            user = prompts.build_persona_user_prompt(name, team_text)
            team = ask(
                deps.llm,
                prompts.PERSONA_SYSTEM_PROMPT,
                user,
                TeamFacts,
                temperature=EXTRACTION_TEMPERATURE,
            )
            people = [
                Person(_clean_name(m.name), m.title.strip(), m.linkedin_url.strip() or None)
                for m in team.people
                if len(_clean_name(m.name).split()) >= 2
            ]
        if not people and inp.target_titles:
            people = search_people(deps.search, name, inp.domain, inp.target_titles)
        return {"people_found": _unique(people)[:MAX_PEOPLE]}

    def fit_node(state: ResearchState) -> ResearchState:
        inp = state["inp"]
        if not inp.icp:
            return {"fit_facts": None}
        site = state.get("site_facts") or SiteFacts()
        signals = state.get("signal_facts") or SignalFacts()
        answers = "\n".join(f"{q}: {a}" for q, a in signals.answers.items() if a)
        user = prompts.build_fit_user_prompt(
            inp.icp, _company(state), site.summary, site.products, inp.notes, answers
        )
        return {
            "fit_facts": ask(
                deps.llm,
                prompts.FIT_SYSTEM_PROMPT,
                user,
                FitFacts,
                temperature=EXTRACTION_TEMPERATURE,
            )
        }

    graph = StateGraph(ResearchState)
    graph.add_node("pages", pages_node)
    graph.add_node(SITE, site_node)
    graph.add_node(LEGAL, legal_node)
    graph.add_node(SIGNALS, signals_node)
    graph.add_node(PERSONA, persona_node)
    graph.add_node("fit", fit_node)
    graph.add_edge(START, "pages")
    graph.add_edge("pages", SITE)
    graph.add_conditional_edges(
        SITE, supervisor, {name: name for name in (LEGAL, SIGNALS, PERSONA, "fit")}
    )
    for worker in (LEGAL, SIGNALS, PERSONA):
        graph.add_edge(worker, "fit")
    graph.add_edge("fit", END)
    return graph.compile()


def search_people(
    search: SearchProvider, company_name: str, domain: str, target_titles: Sequence[str]
) -> list[Person]:
    """People found by a public search on LinkedIn profile titles; profiles are never fetched.

    A person is *confirmed* when the employer on their profile is this company (its whole name,
    or its website's name), and *unconfirmed* when the result only mentions the company. Anyone
    else is dropped: sharing one word ("Grid", "Energy") with the company is not enough.
    """
    titles = " OR ".join(f'"{t}"' for t in target_titles[:4])
    hits = search.search(f'site:linkedin.com/in "{company_name}" ({titles})', max_results=5)
    people: list[Person] = []
    for hit in hits:
        if "linkedin.com/in/" not in hit.url:
            continue
        name, title, employer = read_profile_title(hit.title)
        if len(name.split()) < 2:
            continue
        # "Head of Sales, Volue Power Grid": the employer is often the end of the headline.
        tail = title.rsplit(",", 1)[-1] if "," in title else ""
        if employer_matches(employer, company_name, domain) or employer_matches(
            tail, company_name, domain
        ):
            confirmed = True
        elif not employer and mentions_company(f"{hit.title} {hit.snippet}", company_name, domain):
            confirmed = False
        else:
            continue  # someone at a different company
        url = hit.url.split("?")[0].split("#")[0].rstrip("/")
        people.append(Person(name, title, url, "search", confirmed))
    return people


def _unique(people: Sequence[Person]) -> list[Person]:
    seen: set[str] = set()
    unique: list[Person] = []
    for person in people:
        key = person.name.lower()
        if key not in seen:
            seen.add(key)
            unique.append(person)
    return unique


def run_research(graph: Any, inp: ResearchInput) -> ResearchOutput:
    state: ResearchState = graph.invoke({"inp": inp})
    site = state.get("site_facts") or SiteFacts()
    signals = state.get("signal_facts") or SignalFacts()
    country, country_evidence = state.get("country_facts") or (inp.country_code, "")
    entity, entity_evidence = state.get("legal_facts") or (LegalEntityType.UNKNOWN, "not checked")
    fit = state.get("fit_facts")
    suggestion = state.get("country_suggestion")
    people = tuple(state.get("people_found") or ())
    return ResearchOutput(
        research={
            "summary": site.summary,
            "products": site.products,
            "news": site.news,
            "hooks": site.hooks,
            "hiring": signals.hiring,
            "tech": signals.tech,
            "pages": sorted(state.get("page_text") or {}),
            "site_emails": published_addresses(state.get("page_text") or {}, inp.domain),
            "thin": bool(state.get("thin")),
            "country_evidence": country_evidence,
            "country_suggestion": (
                {"code": suggestion[0], "evidence": suggestion[1]} if suggestion else None
            ),
            "legal_evidence": entity_evidence,
            "workers": plan_workers(inp),
        },
        answers=signals.answers,
        country_code=country,
        legal_entity_type=entity,
        fit_score=fit.score if fit else None,
        fit_reason=fit.reason if fit else None,
        people=people,
        company_name=(site.company_name.strip() or None),
    )
