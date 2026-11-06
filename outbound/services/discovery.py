"""Finding new companies for a campaign: look in several places, screen, add the best.

A run works from the campaign's brief (``outbound.domain.brief``; drafted on the first run if
nobody has). It asks every source that suits the brief (``domain.discovery.plan_sources``):

- start-up directories such as Y Combinator, which name companies with a description;
- pages that list many companies (rankings, funding round-ups, cohorts), found by web search and
  read by a model, which reports each company the page describes and what it says about it.

Everything found is merged (a company named by two sources is one company, found twice), the
companies already screened for this campaign or already leads are set aside, and the rest are
screened against the brief by a model in batches. The best fits get a website (from the source,
or one search) and are added as leads, up to the run's count; the discovery credit is charged
then, as before. Every company is remembered with its verdict (``discovery_candidates``), so
none is screened twice, and every page read and search made is recorded on the run.

Every paid call is metered: the sources, the searches and the model arrive behind the meter.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from outbound.db.types import utcnow
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.actors import SYSTEM
from outbound.domain.brief import Brief
from outbound.domain.discovery import (
    ARTICLES,
    YIELD_DAYS,
    article_queries,
    clean,
    name_key,
    plan_sources,
    share,
)
from outbound.domain.domains import is_free_mail, is_platform, registrable_domain
from outbound.domain.entities import Campaign
from outbound.domain.enums import (
    CandidateVerdict,
    CompanySource,
    EntityType,
    ImportRowStatus,
    ImportSource,
)
from outbound.logging import get_logger
from outbound.prompts.discovery import (
    EXTRACT_SYSTEM_PROMPT,
    SCREEN_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    extract_user_prompt,
    screen_user_prompt,
    user_prompt,
)
from outbound.providers.errors import ProviderError
from outbound.providers.llm_json import parse_json_object
from outbound.providers.ports import (
    CompanyMention,
    LeadSource,
    LlmClient,
    SearchProvider,
    SourceQuery,
)
from outbound.services.brief import draft_brief
from outbound.services.intake import DomainResolver, IntakeService

log = get_logger(__name__)

HISTORY = 30  # how many earlier searches a run remembers and avoids
MAX_SEARCHES = 4  # article searches per run: enough angles, not a runaway bill
PAGES_PER_SEARCH = 3  # the best list pages a search finds; one extract credit reads five
PAGE_CHARS = 12_000  # of each page the model reads
PER_SOURCE = 25  # companies asked of each directory, before weighting by its record
EXAMPLES = 3  # qualified leads given to lookalike sources as examples
SCREEN_BATCH = 15  # companies screened per model call
SCREEN_MIN = 50  # below this a company does not fit
MIN_CONFIDENCE = 0.65  # a website found by search below this is not trusted
ENOUGH = 4  # stop searching for articles once this many fresh companies per wanted lead exist
CORROBORATION_BONUS = 5  # per extra source that named the same company, up to three


@dataclass(frozen=True)
class PlannedQuery:
    q: str
    angle: str = ""


@dataclass(frozen=True)
class Screening:
    score: int | None
    reason: str
    fits: bool


@dataclass
class Found:
    """One company, merged from every source that named it."""

    key: str
    name: str
    domain: str | None = None
    description: str = ""
    evidence: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)

    @property
    def corroboration(self) -> int:
        return len(self.sources)


@dataclass(frozen=True)
class Discovery:
    added: int = 0
    already_leads: int = 0
    searches: int = 0
    found: int = 0
    rejected: int = 0


# --------------------------------------------------------------------------- planning


def plan_queries(
    *, llm: LlmClient | None, brief: Brief, used: Sequence[str], count: int
) -> list[PlannedQuery]:
    """Up to ``count`` new searches for pages that list companies like the ones wanted. The
    model writes them from the brief; the brief's own words fill any gap (no model, or an
    unusable answer)."""
    planned: list[PlannedQuery] = []
    if llm is not None:
        try:
            reply = llm.complete(
                SYSTEM_PROMPT,
                user_prompt(brief, used, count),
                json_mode=True,
                temperature=0.9,  # new angles, not the same ones again
                max_tokens=800,
            )
            raw = parse_json_object(llm.name, reply.text).get("queries", [])
            planned = _planned(raw if isinstance(raw, list) else [], used=used, limit=count)
        except ProviderError as error:
            log.warning("discovery_planning_failed", reason=str(error)[:200])
    if len(planned) < count:
        taken = [*used, *(p.q for p in planned)]
        planned += [
            PlannedQuery(q, "from the brief")
            for q in article_queries(brief, used=taken, limit=count - len(planned))
        ]
    return planned


def _planned(raw: Iterable[object], *, used: Sequence[str], limit: int) -> list[PlannedQuery]:
    angles: dict[str, str] = {}
    texts: list[object] = []
    for item in raw:
        q = item.get("q") if isinstance(item, Mapping) else item
        if isinstance(q, str):
            texts.append(q)
            angle = item.get("angle") if isinstance(item, Mapping) else ""
            angles[" ".join(q.split())] = str(angle or "")[:80]
    return [PlannedQuery(q, angles.get(q, "")) for q in clean(texts, used=used, limit=limit)]


def source_query(brief: Brief, *, examples: Sequence[str] = ()) -> SourceQuery:
    """What a directory is asked, from the brief; ``examples`` are the websites of leads that
    qualified, which lookalike sources find more like, after the brief's own examples."""
    return SourceQuery(
        keywords=brief.keywords or brief.segments,
        segments=brief.segments,
        regions=brief.regions,
        founded_after=brief.founded_after,
        industry_codes=brief.industry_codes,
        text=brief.summary,
        seed_domains=tuple(dict.fromkeys([*brief.seed_companies, *examples])),
    )


# --------------------------------------------------------------------------- articles


class ArticleSource:
    """Pages that list companies, found by web search and read by a model. ``query.text`` is
    the search. Pages in ``skip`` (read by an earlier run) are not read again; every page read
    is added to it and listed in ``read``."""

    name = ARTICLES

    def __init__(self, search: SearchProvider, llm: LlmClient, *, skip: set[str]) -> None:
        self._search = search
        self._llm = llm
        self._skip = skip
        self.read: list[str] = []

    def find(self, query: SourceQuery, *, limit: int) -> list[CompanyMention]:
        self.read = []
        urls: list[str] = []
        for hit in self._search.search(query.text, max_results=8):
            if hit.url in self._skip or hit.url in urls or hit.url.lower().endswith(".pdf"):
                continue
            urls.append(hit.url)
            if len(urls) >= PAGES_PER_SEARCH:
                break
        if not urls:
            return []
        # What was asked for is what counts as read: a page that could not be fetched is not
        # tried again either, and a vendor may return a page under a slightly different address.
        self.read = urls
        self._skip.update(urls)
        mentions: list[CompanyMention] = []
        for page in self._search.extract(urls):
            mentions += self._read(page.url, page.text[:PAGE_CHARS])
        return mentions[:limit]

    def _read(self, url: str, text: str) -> list[CompanyMention]:
        try:
            reply = self._llm.complete(
                EXTRACT_SYSTEM_PROMPT,
                extract_user_prompt(url, text),
                json_mode=True,
                temperature=0.1,
                max_tokens=2_000,
            )
            companies = parse_json_object(self._llm.name, reply.text).get("companies", [])
        except ProviderError as error:
            log.warning("discovery_page_unread", reason=str(error)[:200])
            return []
        out: list[CompanyMention] = []
        for item in companies if isinstance(companies, list) else []:
            if not isinstance(item, Mapping):
                continue
            name = " ".join(str(item.get("name") or "").split())[:200]
            if not name_key(name):
                continue
            said = " ".join(str(item.get("what_it_says") or "").split())[:500]
            out.append(
                CompanyMention(
                    name=name,
                    domain=_usable_domain(str(item.get("website") or "")),
                    description=said,
                    source=ARTICLES,
                    source_url=url,
                    evidence=said,
                )
            )
        return out


def _usable_domain(value: str) -> str | None:
    domain = registrable_domain(value) if value.strip() else None
    if not domain or is_platform(domain) or is_free_mail(domain):
        return None
    return domain


# --------------------------------------------------------------------------- merging, screening


def merge(mentions: Iterable[CompanyMention]) -> list[Found]:
    """One entry per company: the same website, or failing that the same name, is the same
    company. The longest description is kept; every source, page and piece of evidence too."""
    by_key: dict[str, Found] = {}
    by_domain: dict[str, str] = {}
    for m in mentions:
        key = name_key(m.name)
        if not key:
            continue
        domain = _usable_domain(m.domain or "")
        key = by_domain.get(domain, key) if domain else key
        found = by_key.setdefault(key, Found(key=key, name=m.name))
        if domain and not found.domain:
            found.domain = domain
            by_domain[domain] = key
        if len(m.description) > len(found.description):
            found.description = m.description
        if m.evidence and m.evidence not in found.evidence:
            found.evidence.append(m.evidence)
        if m.source not in found.sources:
            found.sources.append(m.source)
        if m.source_url and m.source_url not in found.source_urls:
            found.source_urls.append(m.source_url)
    return list(by_key.values())


def screen(llm: LlmClient | None, brief: Brief, found: Sequence[Found]) -> dict[str, Screening]:
    """Each company's fit with the brief, by key. With no model, or when a batch fails, a
    company fits when its description uses the brief's own words."""
    out: dict[str, Screening] = {}
    for start in range(0, len(found), SCREEN_BATCH):
        batch = found[start : start + SCREEN_BATCH]
        judged = _judge(llm, brief, batch) if llm is not None else {}
        for n, item in enumerate(batch, start=1):
            out[item.key] = judged.get(n) or _by_words(brief, item)
    return out


def _judge(llm: LlmClient, brief: Brief, batch: Sequence[Found]) -> dict[int, Screening]:
    listed = [(f.name, f.domain or "", f.description, " / ".join(f.evidence)) for f in batch]
    try:
        reply = llm.complete(
            SCREEN_SYSTEM_PROMPT,
            screen_user_prompt(brief, listed),
            json_mode=True,
            temperature=0.1,
            max_tokens=200 + 120 * len(batch),
        )
        companies = parse_json_object(llm.name, reply.text).get("companies", [])
    except ProviderError as error:
        log.warning("discovery_screening_failed", reason=str(error)[:200])
        return {}
    judged: dict[int, Screening] = {}
    for item in companies if isinstance(companies, list) else []:
        if not isinstance(item, Mapping) or not isinstance(item.get("n"), int):
            continue
        score = item.get("score")
        score = min(max(score, 0), 100) if isinstance(score, int) else 0
        out_by = [str(d) for d in item.get("disqualified_by") or [] if str(d).strip()]
        reason = " ".join(str(item.get("reason") or "").split())[:300]
        fits = score >= SCREEN_MIN and not out_by
        judged[item["n"]] = Screening(score, reason or "; ".join(out_by), fits)
    return judged


def _by_words(brief: Brief, item: Found) -> Screening:
    words = [w.lower() for w in (*brief.keywords, *brief.segments) if w.strip()]
    if not words:
        return Screening(None, "no brief to screen against", True)
    text = f"{item.name} {item.description} {' '.join(item.evidence)}".lower()
    hit = next((w for w in words if w in text), None)
    if hit:
        return Screening(None, f"its description mentions {hit!r}", True)
    return Screening(None, "nothing it says matches the brief", False)


def rank_score(item: Found, screening: Screening) -> int:
    bonus = CORROBORATION_BONUS * min(item.corroboration - 1, 3)
    return (screening.score if screening.score is not None else SCREEN_MIN) + bonus


# --------------------------------------------------------------------------- a run


@dataclass
class Discoverer:
    """One discovery run for one workspace. Everything paid arrives metered."""

    uow: UnitOfWorkFactory
    workspace_id: str
    intake: IntakeService
    search: SearchProvider
    llm: LlmClient | None
    sources: Sequence[LeadSource] = ()
    resolve: Callable[[str], tuple[str | None, float | None]] | None = None

    def run(
        self, campaign: Campaign, profile: Mapping[str, Any], count: int, run_id: str | None
    ) -> Discovery:
        brief = self._brief(campaign, profile)
        with self.uow(self.workspace_id) as uow:
            known_domains = uow.companies.known_domains()
            known_keys = uow.candidates.known_keys(campaign.id)
            read = uow.candidates.read_urls(campaign.id)
            yields = uow.candidates.source_yield(since=utcnow() - timedelta(days=YIELD_DAYS))
            examples = uow.companies.qualified_domains(campaign.id, EXAMPLES)
            earlier = uow.events.latest(
                EntityType.WORKSPACE, self.workspace_id, "discovery_query", HISTORY * 4
            )
        mine = [e.data for e in reversed(earlier) if e.data.get("campaign") == campaign.name]
        # Article searches already run, oldest first, and every page they read.
        used = [str(d.get("query", "")) for d in mine if d.get("source", ARTICLES) == ARTICLES]
        used = used[-HISTORY:]
        read |= {str(url) for d in mine for url in d.get("pages") or []}

        # Fits an earlier run had no room for go first: already screened, so free to add.
        added = self._take_waiting(campaign, run_id, count, known_domains)
        if added >= count:
            log.info("discovery_done", asked=count, calls=0, found=0, added=added)
            return Discovery(added=added)

        available = {s.name for s in self.sources} | ({ARTICLES} if self.llm else set())
        mentions: list[CompanyMention] = []
        calls = 0
        # Sources whose leads qualified most often go first and are asked for more.
        for name in plan_sources(brief, available=available, yields=yields):
            weight = share(name, yields)
            if name == ARTICLES and self.llm is not None:
                searches = max(1, round(MAX_SEARCHES * weight))
                mentions, made = self._articles(self.llm, brief, campaign, mentions, used, read,
                                                known_keys, count, run_id, searches)  # fmt: skip
                calls += made
                continue
            source = next(s for s in self.sources if s.name == name)
            query = source_query(brief, examples=examples)
            try:
                got = source.find(query, limit=max(1, int(PER_SOURCE * weight)))
            except ProviderError as error:
                log.warning("discovery_source_failed", source=name, reason=str(error)[:200])
                got = []
            calls += 1
            mentions += got
            self._record(campaign, run_id, source=name, query=", ".join(query.keywords),
                         angle="directory", pages=[], found=len(got))  # fmt: skip

        merged = [f for f in merge(mentions) if f.key not in known_keys]
        already = [f for f in merged if f.domain and f.domain in known_domains]
        fresh = [f for f in merged if not (f.domain and f.domain in known_domains)]
        screenings = screen(self.llm, brief, fresh)
        fresh.sort(key=lambda f: -rank_score(f, screenings[f.key]))

        rejected = 0
        for item in already:
            self._keep(
                campaign, run_id, item, None, CandidateVerdict.ALREADY_LEAD, "a lead already"
            )
        for item in fresh:
            screening = screenings[item.key]
            if not screening.fits:
                rejected += 1
                self._keep(campaign, run_id, item, screening, CandidateVerdict.REJECTED,
                           screening.reason)  # fmt: skip
                continue
            if added >= count:
                self._keep(campaign, run_id, item, screening, CandidateVerdict.OVER_LIMIT,
                           "fits; the run had found enough")  # fmt: skip
                continue
            verdict, why, company_id = self._place(campaign, item, known_domains)
            added += verdict is CandidateVerdict.ACCEPTED
            self._keep(campaign, run_id, item, screening, verdict, why or screening.reason,
                       company_id=company_id)  # fmt: skip
        log.info("discovery_done", asked=count, calls=calls, found=len(merged), added=added,
                 rejected=rejected, already_leads=len(already))  # fmt: skip
        return Discovery(added, len(already), calls, len(merged), rejected)

    # ----------------------------------------------------------------------- steps

    def _brief(self, campaign: Campaign, profile: Mapping[str, Any]) -> Brief:
        brief = Brief.from_json(campaign.icp_brief)
        if not brief.is_empty:
            return brief
        brief = draft_brief(self.llm, campaign=campaign, profile=profile)
        with self.uow(self.workspace_id) as uow:
            uow.campaigns.update(campaign.id, {"icp_brief": brief.to_json()})
            uow.events.append(EntityType.WORKSPACE, self.workspace_id, "campaign_brief_drafted",
                              SYSTEM, {"campaign_id": campaign.id})  # fmt: skip
            uow.commit()
        return brief

    def _articles(
        self,
        llm: LlmClient,
        brief: Brief,
        campaign: Campaign,
        mentions: list[CompanyMention],
        used: list[str],
        read: set[str],
        known_keys: set[str],
        count: int,
        run_id: str | None,
        searches: int,
    ) -> tuple[list[CompanyMention], int]:
        source = ArticleSource(self.search, llm, skip=read)
        made = 0
        for planned in plan_queries(llm=llm, brief=brief, used=used, count=searches):
            fresh = {name_key(m.name) for m in mentions} - known_keys
            if len(fresh) >= count * ENOUGH:
                break
            got = source.find(SourceQuery(text=planned.q), limit=PER_SOURCE * 2)
            made += 1
            mentions = [*mentions, *got]
            self._record(campaign, run_id, source=ARTICLES, query=planned.q,
                         angle=planned.angle, pages=source.read, found=len(got))  # fmt: skip
        return mentions, made

    def _take_waiting(
        self, campaign: Campaign, run_id: str | None, count: int, known_domains: set[str]
    ) -> int:
        with self.uow(self.workspace_id) as uow:
            waiting = uow.candidates.waiting(campaign.id, count)
        added = 0
        for candidate in waiting:
            item = Found(
                key=candidate.name_key,
                name=candidate.name,
                domain=candidate.domain,
                description=candidate.description,
                evidence=[candidate.evidence] if candidate.evidence else [],
                sources=list(candidate.sources),
                source_urls=list(candidate.source_urls),
            )
            verdict, why, company_id = self._place(campaign, item, known_domains)
            added += verdict is CandidateVerdict.ACCEPTED
            with self.uow(self.workspace_id) as uow:
                uow.candidates.decide(
                    candidate.id, verdict, reason=why or candidate.reason,
                    company_id=company_id, domain=item.domain, run_id=run_id,
                )  # fmt: skip
                uow.commit()
        return added

    def _place(
        self, campaign: Campaign, item: Found, known_domains: set[str]
    ) -> tuple[CandidateVerdict, str, str | None]:
        """Add a company that fits as a lead: its website from the source, or one search."""
        if not item.domain:
            item.domain = self._website(item.name)
        if not item.domain:
            return CandidateVerdict.UNRESOLVED, "fits, but its website could not be confirmed", None
        if item.domain in known_domains:
            return CandidateVerdict.ALREADY_LEAD, "a lead already", None
        company_id, why = self._add(campaign, item)
        if company_id is None:
            return CandidateVerdict.REJECTED, why, None
        known_domains.add(item.domain)
        return CandidateVerdict.ACCEPTED, "", company_id

    def _website(self, name: str) -> str | None:
        if self.resolve is None:
            return None
        domain, confidence = self.resolve(name)
        if not domain or (confidence or 0) < MIN_CONFIDENCE:
            return None
        return domain

    def _add(self, campaign: Campaign, item: Found) -> tuple[str | None, str]:
        note = "Found by discovery ({}): {}".format(
            ", ".join(item.sources), " | ".join([*item.evidence[:2], *item.source_urls[:2]])
        )
        report = self.intake.run(
            [{"website": item.domain, "company": item.name, "notes": note[:1_000]}],
            source=ImportSource.CLI,
            company_source=CompanySource.DISCOVERY,
            campaign_id=campaign.id,
        )
        [row] = report.rows
        if row.status is not ImportRowStatus.ACCEPTED:
            return None, row.reason or row.status.value
        with self.uow(self.workspace_id) as uow:
            company = uow.companies.by_domain(item.domain or "")
        return (company.id if company else None), ""

    def _keep(
        self,
        campaign: Campaign,
        run_id: str | None,
        item: Found,
        screening: Screening | None,
        verdict: CandidateVerdict,
        reason: str,
        *,
        company_id: str | None = None,
    ) -> None:
        with self.uow(self.workspace_id) as uow:
            uow.candidates.add(
                campaign_id=campaign.id,
                run_id=run_id,
                name=item.name,
                name_key=item.key,
                domain=item.domain,
                sources=item.sources,
                source_urls=item.source_urls,
                description=item.description,
                evidence=" | ".join(item.evidence)[:2_000],
                screen_score=screening.score if screening else None,
                rank_score=rank_score(item, screening) if screening else None,
                verdict=verdict,
                reason=reason,
                company_id=company_id,
            )
            uow.commit()

    def _record(
        self,
        campaign: Campaign,
        run_id: str | None,
        *,
        source: str,
        query: str,
        angle: str,
        pages: Sequence[str],
        found: int,
    ) -> None:
        """Remembered, so the next run takes a different angle; shown on the run's page."""
        with self.uow(self.workspace_id) as uow:
            uow.events.append(
                EntityType.WORKSPACE, self.workspace_id, "discovery_query", SYSTEM,
                {"query": query, "campaign": campaign.name, "run_id": run_id, "source": source,
                 "angle": angle, "pages": list(pages), "found": found},
            )  # fmt: skip
            uow.commit()


def domain_resolver(search: SearchProvider) -> Callable[[str], tuple[str | None, float | None]]:
    """One search for a company's website by its name (``intake.DomainResolver``)."""
    resolver = DomainResolver(search)

    def resolve(name: str) -> tuple[str | None, float | None]:
        found = resolver.by_name(name)
        return found.domain, found.confidence

    return resolve
