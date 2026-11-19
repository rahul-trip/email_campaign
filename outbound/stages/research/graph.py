"""Research as a small LangGraph: fetch pages, let a supervisor pick workers, then score fit.

The graph is used as a stateless function: it takes what is known about one company and returns
what research found, with no checkpointer and no database access. Everything it spends goes
through the metered providers handed in, so each search and model call is cached, capped and
costed like any other.

    pages -> site -> (supervisor picks) -> legal | signals | persona -> fit

When the campaign has a brief, the site worker also checks its disqualifiers, and a discovered
lead the pages clearly rule out goes straight to ``fit`` (``after_site``): no news, legal,
signals or people searches are spent on it. ``fit`` then judges the company criterion by
criterion and scores it in plain code (``outbound.domain.qualification``).

The site worker runs first because it reads the company's own name, and the later workers
search with it: a discovered lead arrives with no name, and a search made with a page title
instead finds the wrong people.

The supervisor is plain code (``plan_workers``) so its routing rules are unit-tested.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Hashable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from functools import partial
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field, field_validator

from outbound.domain.brief import Brief
from outbound.domain.domains import registrable_domain
from outbound.domain.enums import LegalEntityType
from outbound.domain.names import clean_person_name, mentions_company, read_profile_title
from outbound.domain.placement import Placement, place_by_rules
from outbound.domain.qualification import Check, checks, qualify
from outbound.domain.ranking import is_decision_maker, is_role
from outbound.logging import get_logger
from outbound.prompts import research as prompts
from outbound.providers.errors import BudgetExceeded, ProviderError
from outbound.providers.llm_json import ask_json as ask
from outbound.providers.ports import (
    CompanyRegistry,
    LlmClient,
    PageText,
    SearchHit,
    SearchProvider,
)
from outbound.stages.research.employment import Candidate, judge_people
from outbound.stages.research.facts import (
    CountryInference,
    best_registry_match,
    classify_legal_entity,
    find_incorporation_markers,
    infer_country,
)
from outbound.stages.research.linkedin import find_linkedin_many
from outbound.stages.together import together, together_tolerant

log = get_logger(__name__)

PAGE_PATHS = ("", "/about", "/team", "/news", "/contact")  # five URLs = one extract credit
# Generous, so no page is cut short before the model reads it (one extract credit either way).
PAGE_CHARS = 12_000
TOTAL_CHARS = 40_000
TEAM_HINTS = (
    "team", "leadership", "people", "about", "management", "board", "founder", "executive",
)  # fmt: skip
# Links worth following from the front pages to find who runs the company, best first.
TEAM_LINK_WORDS = (
    "leadership", "management", "team", "executive", "board", "founder", "people", "about",
    "who-we-are", "our-story", "company",
)  # fmt: skip
MAX_TEAM_PAGES = 3  # one more extract request at most
LINKEDIN_LOOKUPS = 10  # one search each; the lead page's button covers the rest
MAX_PEOPLE = 25  # a guard against a page that lists a whole company; nobody real is dropped
COMPANY_NEWS_DAYS = 180
MARKET_NEWS_DAYS = 90
MARKET_TERMS = "(regulation OR tender OR market OR funding OR acquisition)"
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
    brief: Brief | None = None
    operator_chosen: bool = False  # typed, imported or referred: never ruled out early


@dataclass(frozen=True)
class Person:
    name: str
    title: str = ""
    linkedin_url: str | None = None
    source: str = "site"  # "site" or "search"
    # Whether they work at the company. A person the site names is placed; a search's find is
    # placed by rules, then by a model (see ``stages/research/employment.py``).
    placement: Placement = Placement.WORKS_HERE
    reason: str = ""
    evidence: str = ""  # what the search showed of them; read once, never saved


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


class _RuledOut(_Reply):
    id: str = ""
    evidence: str = ""


class _TeamMember(_Reply):
    name: str = ""
    title: str = ""
    linkedin_url: str = ""


class SiteFacts(_Reply):
    sector: str = ""
    company_name: str = ""
    summary: str = ""
    products: list[str] = Field(default_factory=list)
    news: list[str] = Field(default_factory=list)
    hooks: list[str] = Field(default_factory=list)
    ruled_out: list[_RuledOut] = Field(default_factory=list)
    people: list[_TeamMember] = Field(default_factory=list)  # from the team pages, same call


class _NewsPick(_Reply):
    n: int = 0
    detail: str = ""
    matters: str = ""


class NewsFacts(_Reply):
    company: list[_NewsPick] = Field(default_factory=list)
    market: list[_NewsPick] = Field(default_factory=list)


class SignalFacts(_Reply):
    answers: dict[str, str] = Field(default_factory=dict)
    hiring: str = ""
    tech: list[str] = Field(default_factory=list)


class NewsSignalFacts(NewsFacts, SignalFacts):
    """The news picks and the answers to the campaign's questions, from one call."""


class FitFacts(_Reply):
    score: int = Field(ge=0, le=100)
    reason: str = ""

    @field_validator("score", mode="before")
    @classmethod
    def _clamp(cls, value: object) -> object:
        if isinstance(value, (int, float)):
            return max(0, min(100, round(value)))
        return value


class _Answer(_Reply):
    id: str = ""
    verdict: str = ""
    evidence: str = ""
    source: str = ""


class QualifyFacts(_Reply):
    criteria: list[_Answer] = Field(default_factory=list)
    why_now: str = ""
    risks: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- the supervisor

SITE, LEGAL, SIGNALS, PERSONA, NEWS = "site", "legal", "signals", "persona", "news"


def plan_workers(inp: ResearchInput) -> list[str]:
    """Which workers run for this company. Deterministic, so every rule has a test."""
    workers = [SITE, NEWS]
    if inp.country_code in (None, "GB"):
        workers.append(LEGAL)
    if inp.questions:
        workers.append(SIGNALS)
    if not inp.has_operator_contact:
        workers.append(PERSONA)
    return workers


def _criteria(inp: ResearchInput) -> list[Check]:
    return checks(inp.brief) if inp.brief else []


def _rules(inp: ResearchInput) -> list[Check]:
    return [c for c in _criteria(inp) if c.kind == "disqualifier"]


def site_rulings(inp: ResearchInput, site: SiteFacts) -> dict[str, dict[str, str]]:
    """The brief's disqualifiers the site worker found met, as answers ``qualify`` reads;
    an id the brief does not have is ignored."""
    ids = {c.id for c in _rules(inp)}
    return {
        r.id: {"verdict": "met", "evidence": r.evidence.strip()}
        for r in site.ruled_out
        if r.id in ids
    }


def after_site(inp: ResearchInput, site: SiteFacts) -> list[str]:
    """The workers after the site: none but ``fit`` for a discovered lead its own pages rule
    out, else the planned ones. A lead the operator chose is always researched in full."""
    if not inp.operator_chosen and site_rulings(inp, site):
        return ["fit"]
    return [w for w in plan_workers(inp) if w != SITE] or ["fit"]


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
    news_items: list[dict[str, str]]
    triggers: list[dict[str, str]]
    people_found: list[Person]
    fit_facts: FitFacts | None
    qualification: dict[str, Any]


def _joined(pages: dict[str, str], *, only: Sequence[str] = (), without: Sequence[str] = ()) -> str:
    parts: list[str] = []
    used = 0
    for url, text in pages.items():
        if only and not any(hint in url.lower() for hint in only):
            continue
        if without and any(hint in url.lower() for hint in without):
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
    return found


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
        pages = deps.search.extract(urls, links=True)
        found = {page.url: page.text for page in pages if page.text.strip()}
        if found:
            # The fixed paths guess where a team page is; the site's own links say. Pages that
            # name who runs the company are read too, so the people are not just whoever the
            # home page mentions.
            more = team_links(pages, inp.domain, read=set(found))
            if more:
                try:
                    found |= {p.url: p.text for p in deps.search.extract(more) if p.text.strip()}
                except BudgetExceeded:
                    raise
                except ProviderError as error:
                    log.warning("team_pages_unread", reason=str(error)[:200])
            return {"page_text": found, "thin": False}
        # The site could not be read: fall back to what a search says about the company.
        hits = deps.search.search(f"{inp.company_name} {inp.domain}", max_results=5)
        snippets = {hit.url: f"{hit.title}. {hit.snippet}" for hit in hits if hit.snippet}
        return {"page_text": snippets, "thin": True}

    def supervisor(state: ResearchState) -> list[Hashable]:
        # The signals are answered inside the news node, in the same model call.
        workers = after_site(state["inp"], state.get("site_facts") or SiteFacts())
        return list[Hashable]([w for w in workers if w != SIGNALS] or ["fit"])

    def site_node(state: ResearchState) -> ResearchState:
        inp = state["inp"]
        # The team pages go in their own block, read in the same call for the people on them
        # (one model call instead of two), with their own length cap so none are cut short.
        # When the site could not be read the text is other sites' snippets: no people from it.
        team = (
            _joined(state["page_text"], only=TEAM_HINTS)
            if not state.get("thin") and not inp.has_operator_contact
            else ""
        )
        team = team if len(team) > MIN_TEAM_TEXT else ""
        user = prompts.build_site_user_prompt(
            inp.company_name,
            inp.domain,
            _joined(state["page_text"], without=TEAM_HINTS if team else ()),
            [f"{c.id}. {c.text}" for c in _rules(inp)],
            team=team,
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

    def news_node(state: ResearchState) -> ResearchState:
        """Recent news and, when the campaign asks questions, the answers and the hiring and
        technology signals: the searches first, then one model call for all of it."""
        inp = state["inp"]
        name = _company(state)
        site = state.get("site_facts") or SiteFacts()
        asks = bool(inp.questions)

        def company_news() -> list[SearchHit]:
            hits = _dated(
                deps.search.search(
                    f'"{name}"', max_results=8, topic="news", days=COMPANY_NEWS_DAYS
                ),
                COMPANY_NEWS_DAYS,
            )
            # A news hit must use the company's whole name. The website's name alone is not enough
            # here: "Acme" matches every Acme in the news, and a wrong story is worse than none.
            return [h for h in hits if mentions_company(f"{h.title} {h.snippet}", name, "")]

        def market_news() -> list[SearchHit]:
            if not site.sector.strip():
                return []
            return _dated(
                deps.search.search(
                    f"{site.sector.strip()} {MARKET_TERMS}",
                    max_results=6,
                    topic="news",
                    days=MARKET_NEWS_DAYS,
                ),
                MARKET_NEWS_DAYS,
            )

        def careers() -> list[SearchHit]:
            return deps.search.search(
                f"{name} {inp.domain} careers hiring technology", max_results=5
            )

        # The searches do not depend on each other, so they are made together.
        found = together_tolerant([company_news, market_news, *([careers] if asks else [])])
        company_hits: list[SearchHit] = []
        market_hits: list[SearchHit] = []
        if isinstance(found[0], ProviderError) or isinstance(found[1], ProviderError):
            # News makes the email better but is not worth failing the lead for.
            failed = found[0] if isinstance(found[0], ProviderError) else found[1]
            log.warning("news_search_failed", reason=str(failed)[:200])
        else:
            company_hits, market_hits = found[0], found[1]
        careers_hits: list[SearchHit] = []
        if asks:
            if isinstance(found[2], ProviderError):
                raise found[2]  # as before: the signals need this search
            careers_hits = found[2]
        if not asks and not company_hits and not market_hits:
            return {"news_items": [], "triggers": []}
        company_list = _numbered(company_hits)
        market_list = _numbered(market_hits, start=len(company_hits) + 1)
        picked: NewsFacts
        if asks:
            picked = ask(
                deps.llm,
                prompts.NEWS_SIGNALS_SYSTEM_PROMPT,
                prompts.build_news_signals_user_prompt(
                    company=name,
                    sector=site.sector,
                    summary=site.summary,
                    company_hits=company_list,
                    market_hits=market_list,
                    questions=inp.questions,
                    pages=_joined(state["page_text"]),
                    search_snippets="\n".join(f"- {h.title}: {h.snippet}" for h in careers_hits),
                ),
                NewsSignalFacts,
                temperature=EXTRACTION_TEMPERATURE,
            )
        else:
            picked = ask(
                deps.llm,
                prompts.NEWS_SYSTEM_PROMPT,
                prompts.build_news_user_prompt(
                    name, site.sector, site.summary, company_list, market_list
                ),
                NewsFacts,
                temperature=EXTRACTION_TEMPERATURE,
            )
        everything = [*company_hits, *market_hits]  # numbering is continuous across both lists

        def items(picks: list[_NewsPick], allowed: range) -> list[dict[str, str]]:
            found: list[dict[str, str]] = []
            for pick in picks:
                if pick.n in allowed and pick.detail.strip():
                    hit = everything[pick.n - 1]
                    found.append(
                        {
                            "date": _iso_date(hit.published_date) or "",
                            "headline": hit.title.strip(),
                            "detail": " ".join(pick.detail.split()),
                            "matters": " ".join(pick.matters.split()),
                            "url": hit.url,
                        }
                    )
            return found

        company_range = range(1, len(company_hits) + 1)
        market_range = range(len(company_hits) + 1, len(everything) + 1)
        update: ResearchState = {
            "news_items": items(picked.company, company_range),
            "triggers": items(picked.market, market_range),
        }
        if isinstance(picked, NewsSignalFacts):
            update["signal_facts"] = SignalFacts(
                answers=picked.answers, hiring=picked.hiring, tech=picked.tech
            )
        return update

    def persona_node(state: ResearchState) -> ResearchState:
        inp = state["inp"]
        name = _company(state)
        people: list[Person] = []
        # The site call already read the team pages for their people (see ``site_node``); when
        # the site could not be read there are none, and only the public search below is used.
        if not state.get("thin"):
            people = [
                Person(_clean_name(m.name), m.title.strip(), m.linkedin_url.strip() or None)
                for m in (state.get("site_facts") or SiteFacts()).people
                if len(_clean_name(m.name).split()) >= 2
            ]
        # Nobody on the site who can decide (or nobody at all): ask the public search, which
        # finds people by the campaign's job titles, and keep both lists.
        if inp.target_titles and not any(
            is_decision_maker(p.title, inp.target_titles) for p in people
        ):
            people = [
                *people,
                *search_people(
                    deps.search,
                    name,
                    inp.domain,
                    inp.target_titles,
                    "" if state.get("thin") else _joined(state["page_text"]),
                ),
            ]
        found = _judge(_unique(people)[:MAX_PEOPLE], deps.llm, name, inp.domain, state)
        # People with no profile link are looked up a few names per search (a button on the
        # lead page looks again for anyone past the limit, or whose search found nothing).
        wanted = [
            p.name for p in found if not p.linkedin_url and p.placement is not Placement.NOT_HERE
        ][:LINKEDIN_LOOKUPS]
        links = find_linkedin_many(deps.search, wanted, name, inp.domain) if wanted else {}
        found = [
            replace(p, linkedin_url=links[p.name]) if not p.linkedin_url and p.name in links else p
            for p in found
        ]
        return {"people_found": found}

    def qualify_node(state: ResearchState, criteria: list[Check]) -> ResearchState:
        inp = state["inp"]
        brief = inp.brief or Brief()
        site = state.get("site_facts") or SiteFacts()
        early = site_rulings(inp, site)
        if early and not inp.operator_chosen:
            # The pages already rule it out: no model call is worth making.
            result, why_now, risks = qualify(brief, early), "", []
        else:
            signals = state.get("signal_facts") or SignalFacts()
            user = prompts.build_qualify_user_prompt(
                brief=brief.summary or inp.icp,
                criteria=[
                    f"{c.id}. {c.text}" + (f" (counts {c.weight})" if c.weight > 1 else "")
                    for c in criteria
                ],
                company=_company(state),
                research=_findings(state),
                notes=inp.notes,
                answers="\n".join(f"{q}: {a}" for q, a in signals.answers.items() if a),
                pages=_joined(state["page_text"]),
            )
            reply = ask(
                deps.llm,
                prompts.QUALIFY_SYSTEM_PROMPT,
                user,
                QualifyFacts,
                temperature=EXTRACTION_TEMPERATURE,
            )
            answers = {a.id: a.model_dump() for a in reply.criteria}
            # A disqualifier the site saw stands even if this reply forgot it.
            answers.update({k: v for k, v in early.items() if k not in answers})
            result = qualify(brief, answers)
            why_now = " ".join(reply.why_now.split())
            risks = [" ".join(r.split()) for r in reply.risks if r.strip()]
        return {
            "fit_facts": FitFacts(score=result.score, reason=result.reason),
            "qualification": {**result.to_json(), "why_now": why_now, "risks": risks},
        }

    def fit_node(state: ResearchState) -> ResearchState:
        inp = state["inp"]
        criteria = _criteria(inp)
        if criteria:
            return qualify_node(state, criteria)
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
    graph.add_node(NEWS, news_node)
    graph.add_node(PERSONA, persona_node)
    graph.add_node("fit", fit_node)
    graph.add_edge(START, "pages")
    graph.add_edge("pages", SITE)
    graph.add_conditional_edges(
        SITE, supervisor, {name: name for name in (LEGAL, PERSONA, NEWS, "fit")}
    )
    for worker in (LEGAL, PERSONA, NEWS):
        graph.add_edge(worker, "fit")
    graph.add_edge("fit", END)
    return graph.compile()


def team_links(pages: Sequence[PageText], domain: str, *, read: Collection[str]) -> list[str]:
    """Links on the pages read that lead to the company's own team, leadership or about pages
    and have not been read: same website, a path or words that say so, best match first, at
    most ``MAX_TEAM_PAGES``."""
    own = registrable_domain(domain)
    seen = {u.rstrip("/").lower() for u in read}
    scored: dict[str, int] = {}
    for page in pages:
        for link in page.links:
            url = link.url.split("#")[0].split("?")[0].rstrip("/")
            if not url or url.lower() in seen or registrable_domain(url) != own:
                continue
            path = url.split("://", 1)[-1].partition("/")[2].lower()
            if not path or path.count("/") > 2 or path.rsplit(".", 1)[-1] in _NOT_PAGES:
                continue
            words = f"{path} {link.text.lower()}"
            hits = [i for i, w in enumerate(TEAM_LINK_WORDS) if w in words]
            if hits:
                scored.setdefault(url, min(hits))
    return sorted(scored, key=lambda u: (scored[u], u))[:MAX_TEAM_PAGES]


_NOT_PAGES = frozenset({"pdf", "jpg", "jpeg", "png", "gif", "svg", "zip", "mp4", "xml"})


def search_people(
    search: SearchProvider,
    company_name: str,
    domain: str,
    target_titles: Sequence[str],
    site_text: str = "",
) -> list[Person]:
    """People found by a public search on LinkedIn profile titles; profiles are never fetched.

    Each is placed by rules (``place_by_rules``): works here, not here, or unsure. A person who
    only shares the company's name, or one word of it ("Grid", "Energy", "Golf"), is not placed
    at the company. Nobody is dropped, so a rerun does not find them again as new.
    """
    roles = [t for t in target_titles if is_role(t)][:4]  # "BESS integrators" finds nobody
    queries = []  # two searches at most, two titles each
    for start in range(0, len(roles), 2):
        titles = " OR ".join(f'"{t}"' for t in roles[start : start + 2])
        queries.append(f'site:linkedin.com/in "{company_name}" ({titles})')
    hits: list[SearchHit] = []
    for found in together([partial(search.search, q, max_results=10) for q in queries]):
        hits += found
    people: list[Person] = []
    for hit in hits:
        if "linkedin.com/in/" not in hit.url:
            continue
        name, title, employer = read_profile_title(hit.title)
        if len(name.split()) < 2:
            continue
        placed = place_by_rules(
            name=name,
            headline=title,
            employer=employer,
            snippet=hit.snippet,
            company=company_name,
            domain=domain,
            site_text=site_text,
        )
        url = hit.url.split("?")[0].split("#")[0].rstrip("/")
        evidence = f"{hit.title.strip()} | {hit.snippet.strip()}"
        people.append(Person(name, title, url, "search", placed.placement, placed.reason, evidence))
    return people


def _iso_date(value: str | None) -> str | None:
    """A vendor's date ("2026-10-18", "Sun, 18 Oct 2026 09:00:00 GMT", ...) as YYYY-MM-DD."""
    text = (value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(text).date().isoformat()
    except (TypeError, ValueError):
        return None


def _dated(hits: Sequence[SearchHit], days: int) -> list[SearchHit]:
    """Only hits with a date that is within the window (not undated, not in the future)."""
    today = datetime.now(UTC).date()
    kept: list[SearchHit] = []
    for hit in hits:
        iso = _iso_date(hit.published_date)
        if iso is None:
            continue
        age = (today - date.fromisoformat(iso)).days
        if 0 <= age <= days + 1:
            kept.append(hit)
    return kept


def _numbered(hits: Sequence[SearchHit], *, start: int = 1) -> str:
    return "\n".join(
        f"{i}. [{_iso_date(h.published_date)}] {h.title.strip()}: {h.snippet.strip()[:300]}"
        for i, h in enumerate(hits, start=start)
    )


def _findings(state: ResearchState) -> str:
    """What the workers found, as the qualifier reads it, with each news item's source."""
    site = state.get("site_facts") or SiteFacts()
    signals = state.get("signal_facts") or SignalFacts()
    lines = [
        f"Sector: {site.sector}",
        f"Summary: {site.summary}",
        "Products: " + "; ".join(site.products),
        "Hiring: " + signals.hiring,
        "Technology: " + "; ".join(signals.tech),
    ]
    for kind, key in (("News", "news_items"), ("Market news", "triggers")):
        for item in state.get(key) or []:  # type: ignore[attr-defined]
            lines.append(f"{kind} ({item['date']}, {item['url']}): {item['detail']}")
    return "\n".join(line for line in lines if not line.endswith(": "))


def _judge(
    people: list[Person], llm: LlmClient, company: str, domain: str, state: ResearchState
) -> list[Person]:
    """Settle the people the rules left unsure, with one model call for all of them."""
    open_ = [i for i, p in enumerate(people) if p.placement is Placement.UNSURE]
    if not open_:
        return people
    site = state.get("site_facts")
    verdicts = judge_people(
        llm,
        company,
        domain,
        site.summary if site else "",
        [Candidate(people[i].name, people[i].evidence) for i in open_],
    )
    settled = list(people)
    for i, (placement, reason) in zip(open_, verdicts, strict=True):
        settled[i] = replace(people[i], placement=placement, reason=reason)
    return settled


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
            "news_items": state.get("news_items") or [],
            "triggers": state.get("triggers") or [],
            "sector": site.sector.strip(),
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
            "workers": [SITE, *(w for w in after_site(inp, site) if w != "fit")],
            **({"qualification": q} if (q := state.get("qualification")) else {}),
        },
        answers=signals.answers,
        country_code=country,
        legal_entity_type=entity,
        fit_score=fit.score if fit else None,
        fit_reason=fit.reason if fit else None,
        people=people,
        company_name=(site.company_name.strip() or None),
    )
