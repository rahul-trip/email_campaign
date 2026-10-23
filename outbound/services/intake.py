"""Stage 1: turn the operator's targets (a file, a typed company, a discovery search) into leads.

Each row is reduced to a root domain, because the domain is what makes a company unique. How
that happens depends on what the operator gave us (the "anchor"):

* a website or domain: used directly;
* a work email: the domain is taken from the address (a free-mail address is not a company);
* a company name, or a person plus company: one web search finds the official site, and a
  match below 0.8 confidence waits as ``needs_confirmation`` for the operator;
* a LinkedIn profile URL: never fetched; a public search on the profile slug names the person
  and company.

Suppression always wins. A domain already in the system is merged, not duplicated: notes are
appended and differing values become events. Searches (which cost money) happen before the
database transaction opens, and one transaction then writes the whole batch.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import openpyxl

from outbound.db.repositories.imports import ImportRowView
from outbound.db.uow import UnitOfWork, UnitOfWorkFactory
from outbound.domain.actors import OPERATOR, SYSTEM
from outbound.domain.countries import country_code
from outbound.domain.domains import is_free_mail, is_platform, registrable_domain
from outbound.domain.enums import (
    CompanySource,
    ContactSource,
    ContactStatus,
    EntityType,
    ImportAnchor,
    ImportRowStatus,
    ImportSource,
    NoteSource,
    Provenance,
)
from outbound.domain.errors import InvalidInput
from outbound.domain.names import (
    company_tokens,
    domain_label,
    read_profile_title,
    split_name,
    split_person,
)
from outbound.logging import get_logger
from outbound.providers.errors import ProviderError
from outbound.providers.ports import SearchHit, SearchProvider

log = get_logger(__name__)

CONFIDENCE_THRESHOLD = 0.8

# Loose header matching: lower-case, letters and digits only, then look up the meaning.
_HEADERS = {
    "company": "company", "companyname": "company", "organization": "company",
    "organisation": "company", "org": "company", "business": "company", "account": "company",
    "name": "company",
    "website": "website", "domain": "website", "url": "website", "site": "website",
    "web": "website", "companywebsite": "website", "organizationurl": "website",
    "organisationurl": "website",
    "email": "email", "emailaddress": "email", "contactemail": "email", "mail": "email",
    "directbusinessemail": "email", "workemail": "email",
    "person": "person", "contact": "person", "contactname": "person", "fullname": "person",
    "specificpersontocontact": "person", "decisionmaker": "person",
    "title": "title", "jobtitle": "title", "role": "title", "position": "title",
    "linkedin": "linkedin", "linkedinurl": "linkedin", "linkedinprofile": "linkedin",
    "profile": "linkedin",
    "country": "country", "countrycode": "country", "location": "country",
    "notes": "notes", "note": "notes", "comments": "notes", "context": "notes",
    "pocdetailseccentricities": "notes",
    "priority": "priority",
}  # fmt: skip

_LINKEDIN_PROFILE = re.compile(r"linkedin\.com/in/([^/?#\s]+)", re.IGNORECASE)


# --------------------------------------------------------------------------- reading a row


@dataclass(frozen=True)
class Target:
    """One row after header matching. ``raw`` is kept exactly as the operator supplied it."""

    raw: Mapping[str, Any]
    company: str = ""
    website: str = ""
    email: str = ""
    person: str = ""
    title: str = ""
    linkedin: str = ""
    country: str = ""
    notes: str = ""
    priority: int | None = None

    @property
    def website_domain(self) -> str | None:
        return registrable_domain(self.website) if self.website else None

    @property
    def email_domain(self) -> str | None:
        return registrable_domain(self.email) if "@" in self.email else None

    @property
    def linkedin_slug(self) -> str | None:
        match = _LINKEDIN_PROFILE.search(self.linkedin)
        return match.group(1) if match else None


def _clean_header(header: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(header).lower())


def parse_target(raw: Mapping[str, Any]) -> Target:
    fields: dict[str, str] = {}
    for header, value in raw.items():
        meaning = _HEADERS.get(_clean_header(header))
        text = "" if value is None else str(value).strip()
        if meaning and text and meaning not in fields:
            fields[meaning] = text
    priority = fields.pop("priority", "")
    return Target(
        raw=dict(raw),
        priority=int(priority) if priority.isdigit() and 1 <= int(priority) <= 9 else None,
        **fields,
    )


def detect_anchor(target: Target) -> ImportAnchor | None:
    if target.website_domain:
        return ImportAnchor.DOMAIN
    email_domain = target.email_domain
    if email_domain and not is_free_mail(email_domain):
        return ImportAnchor.EMAIL
    if target.linkedin_slug and not target.company:
        return ImportAnchor.LINKEDIN_URL
    if target.person and target.company:
        return ImportAnchor.PERSON_COMPANY
    if target.company:
        return ImportAnchor.COMPANY_NAME
    return None


def load_rows(path: Path) -> list[dict[str, Any]]:
    """Read a CSV or XLSX file into dictionaries keyed by its own headers."""
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        return _load_xlsx(path)
    if path.suffix.lower() in {".csv", ".txt"}:
        return _load_csv(path)
    raise InvalidInput(f"{path.name}: expected a .csv or .xlsx file")


def _load_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        try:
            dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(sample, ",;\t")
        except csv.Error:
            dialect = csv.excel
        return [
            {k: v for k, v in row.items() if k is not None}
            for row in csv.DictReader(handle, dialect=dialect)
            if any((v or "").strip() for v in row.values() if isinstance(v, str))
        ]


def _load_xlsx(path: Path) -> list[dict[str, Any]]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        if not workbook.worksheets:
            raise InvalidInput(f"{path.name} has no worksheet")
        rows = workbook.worksheets[0].iter_rows(values_only=True)
        header = [str(cell).strip() if cell is not None else "" for cell in next(rows, ())]
        return [
            dict(zip(header, cells, strict=False))
            for cells in rows
            if any(cell is not None and str(cell).strip() for cell in cells)
        ]
    finally:
        workbook.close()


# --------------------------------------------------------------------------- finding the domain


@dataclass(frozen=True)
class Resolution:
    domain: str | None
    confidence: float | None = None
    note: str | None = None
    person: str = ""  # a name found from a LinkedIn profile
    title: str = ""
    company: str = ""  # a company name found from a LinkedIn profile
    searched: bool = True


def match_confidence(name: str, domain: str, hit: SearchHit) -> float:
    """How sure we are that ``domain`` is the official site of ``name`` (no model involved).

    The website's name must hold the *whole* company name. A site whose name is only part of
    it ("tata.com" for "Tata Power": the parent group's site) is below the threshold, so the
    operator is asked rather than the lead going to the wrong company.
    """
    tokens = company_tokens(name)
    if not tokens:
        return 0.0
    joined = "".join(tokens)
    label = domain_label(domain)
    whole = domain.lower().replace(".", "").replace("-", "")  # "rebase.energy" for Rebase Energy
    if joined in (label, whole):
        return 0.95
    if joined in label:  # "acme" at "acmeenergy.com"
        return 0.85
    text = f"{hit.title} {hit.snippet}".lower()
    if all(token in text for token in tokens):
        return 0.65
    return 0.4


class DomainResolver:
    """Finds a company's official domain with one web search per name."""

    def __init__(self, search: SearchProvider) -> None:
        self._search = search

    def by_name(self, name: str, country: str = "") -> Resolution:
        query = f"{name} official website {country}".strip()
        best: tuple[float, str] | None = None
        for hit in self._search.search(query, max_results=5):
            domain = registrable_domain(hit.url)
            if not domain or is_platform(domain) or is_free_mail(domain):
                continue
            confidence = match_confidence(name, domain, hit)
            if best is None or confidence > best[0]:
                best = (confidence, domain)
        if best is None:
            return Resolution(None, note=f"no website found for {name!r}")
        return Resolution(best[1], best[0])

    def by_linkedin(self, slug: str, country: str = "") -> Resolution:
        words = slug.replace("-", " ").strip()
        hits = self._search.search(f"site:linkedin.com/in {words}", max_results=5)
        for hit in hits:
            if f"/in/{slug.lower()}" not in hit.url.lower():
                continue
            person, title, company = read_profile_title(hit.title)
            if not company:
                break
            found = self.by_name(company, country)
            return Resolution(
                found.domain,
                found.confidence,
                found.note,
                person=person,
                title=title,
                company=company,
            )
        return Resolution(None, note="could not identify a company from that LinkedIn profile")


# --------------------------------------------------------------------------- the report


@dataclass(frozen=True)
class RowOutcome:
    row_number: int | None
    status: ImportRowStatus
    domain: str | None
    reason: str | None
    row_id: str | None = None


@dataclass
class IntakeReport:
    batch_id: str | None
    rows: list[RowOutcome] = field(default_factory=list)
    validate_only: bool = False

    def count(self, status: ImportRowStatus) -> int:
        return sum(1 for row in self.rows if row.status is status)

    @property
    def read(self) -> int:
        return len(self.rows)


@dataclass(frozen=True)
class _Decision:
    status: ImportRowStatus
    domain: str | None
    confidence: float | None = None
    reason: str | None = None
    company_id: str | None = None


# --------------------------------------------------------------------------- the service


class IntakeService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        workspace_id: str,
        search: SearchProvider | None,
        *,
        allow_personal_domain: bool = False,
        actor: str = OPERATOR,
    ) -> None:
        self._uow = uow_factory
        self._workspace_id = workspace_id
        self._resolver = DomainResolver(search) if search else None
        self._allow_personal = allow_personal_domain
        self._actor = actor

    def run(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        source: ImportSource = ImportSource.CLI,
        company_source: CompanySource = CompanySource.MANUAL,
        campaign_id: str | None = None,
        filename: str | None = None,
        validate_only: bool = False,
        actor: str | None = None,
    ) -> IntakeReport:
        """Import ``rows``. With ``validate_only`` nothing is written and no search is made."""
        actor = actor or self._actor
        targets = [parse_target(raw) for raw in rows]
        resolutions = [self._resolve(t, search=not validate_only) for t in targets]

        report = IntakeReport(None, validate_only=validate_only)
        with self._uow(self._workspace_id) as uow:
            if campaign_id:
                uow.campaigns.get(campaign_id)  # NotFound unless it is one of ours
            batch_id = uow.imports.create_batch(
                source, actor, campaign_id=campaign_id, filename=filename
            )
            report.batch_id = None if validate_only else batch_id
            pairs = zip(targets, resolutions, strict=True)
            for number, (target, resolution) in enumerate(pairs, start=2):
                anchor = detect_anchor(target) or ImportAnchor.COMPANY_NAME
                decision = self._decide(
                    uow,
                    target,
                    resolution,
                    anchor,
                    company_source=company_source,
                    campaign_id=campaign_id,
                    actor=actor,
                )
                row_id = uow.imports.add_row(
                    batch_id,
                    dict(target.raw),
                    anchor,
                    decision.status,
                    row_number=number,
                    resolved_domain=decision.domain,
                    resolution_confidence=decision.confidence,
                    reason=decision.reason,
                    company_id=decision.company_id,
                )
                report.rows.append(
                    RowOutcome(number, decision.status, decision.domain, decision.reason, row_id)
                )
            uow.imports.finish_batch(batch_id)
            if validate_only:
                uow.rollback()
            else:
                uow.commit()
        return report

    def needing_confirmation(self) -> list[ImportRowView]:
        with self._uow(self._workspace_id) as uow:
            return uow.imports.rows_with_status(ImportRowStatus.NEEDS_CONFIRMATION)

    def confirm(self, row_id: str, domain: str, *, actor: str | None = None) -> RowOutcome:
        """The operator says which website a waiting row means; the row is then processed."""
        actor = actor or self._actor
        resolved = registrable_domain(domain)
        if resolved is None:
            raise InvalidInput(f"{domain!r} is not a usable domain")
        with self._uow(self._workspace_id) as uow:
            row = uow.imports.get_row(row_id)
            if row.status is not ImportRowStatus.NEEDS_CONFIRMATION:
                raise InvalidInput(f"row is {row.status.value}, not waiting for confirmation")
            target = parse_target(row.raw)
            decision = self._decide(
                uow,
                target,
                Resolution(resolved, 1.0),
                row.anchor,
                company_source=CompanySource.MANUAL,
                campaign_id=uow.imports.batch_campaign(row.batch_id),
                actor=actor,
                confirmed=True,
            )
            uow.imports.settle_row(
                row_id,
                decision.status,
                resolved_domain=decision.domain,
                resolution_confidence=decision.confidence,
                reason=decision.reason,
                company_id=decision.company_id,
            )
            uow.commit()
        return RowOutcome(row.row_number, decision.status, decision.domain, decision.reason, row_id)

    # ------------------------------------------------------------------ resolving (may search)

    def _resolve(self, target: Target, *, search: bool) -> Resolution:
        anchor = detect_anchor(target)
        country = target.country
        if anchor is ImportAnchor.DOMAIN:
            return Resolution(target.website_domain, 1.0, searched=False)
        if anchor is ImportAnchor.EMAIL:
            return Resolution(target.email_domain, 1.0, searched=False)
        if anchor is None:
            return Resolution(None, note=None, searched=False)
        if not search:
            return Resolution(
                None, note="needs a web search (skipped by --validate-only)", searched=False
            )
        if self._resolver is None:
            return Resolution(None, note="no search provider is configured (TAVILY_API_KEY)")
        try:
            if anchor is ImportAnchor.LINKEDIN_URL:
                slug = target.linkedin_slug
                if slug is None:
                    raise InvalidInput("that LinkedIn address is not a profile")
                return self._resolver.by_linkedin(slug, country)
            return self._resolver.by_name(target.company, country)
        except ProviderError as error:
            log.warning(
                "intake_search_failed", error_type=type(error).__name__, reason=str(error)[:200]
            )
            return Resolution(None, note=f"search failed: {error}")

    # ------------------------------------------------------------------ deciding (writes)

    def _decide(
        self,
        uow: UnitOfWork,
        target: Target,
        resolution: Resolution,
        anchor: ImportAnchor,
        *,
        company_source: CompanySource,
        campaign_id: str | None,
        actor: str,
        confirmed: bool = False,
    ) -> _Decision:
        domain = resolution.domain
        if detect_anchor(target) is None:
            email_domain = target.email_domain
            if email_domain and is_free_mail(email_domain):
                return _Decision(
                    ImportRowStatus.REJECTED,
                    None,
                    reason="a free-mail address is not a company, and no company was given",
                )
            return _Decision(
                ImportRowStatus.REJECTED,
                None,
                reason="no company, website, email or LinkedIn profile to go on",
            )
        if domain is None:
            if not resolution.searched:
                return _Decision(ImportRowStatus.PENDING, None, reason=resolution.note)
            return _Decision(ImportRowStatus.NEEDS_CONFIRMATION, None, reason=resolution.note)
        if is_platform(domain) or is_free_mail(domain):
            return _Decision(
                ImportRowStatus.REJECTED, domain, reason=f"{domain} is a platform, not a company"
            )
        if uow.suppressions.is_domain_suppressed(domain):
            return _Decision(ImportRowStatus.REJECTED, domain, reason="domain is suppressed")
        email = target.email.lower()
        if email and uow.suppressions.is_email_suppressed(email):
            return _Decision(ImportRowStatus.REJECTED, domain, reason="email address is suppressed")

        confidence = resolution.confidence
        if not confirmed and confidence is not None and confidence < CONFIDENCE_THRESHOLD:
            return _Decision(
                ImportRowStatus.NEEDS_CONFIRMATION,
                domain,
                confidence,
                reason=f"is {domain} the right website? confidence {confidence:.2f}",
            )

        existing = uow.companies.by_domain(domain)
        if existing is not None:
            self._merge(uow, existing.id, existing.name, existing.country_code, target, actor)
            return _Decision(
                ImportRowStatus.MERGED, domain, confidence, "already a target", existing.id
            )

        company_id, note = self._create(
            uow, domain, target, resolution, company_source, campaign_id, actor
        )
        return _Decision(ImportRowStatus.ACCEPTED, domain, confidence, note, company_id)

    def _create(
        self,
        uow: UnitOfWork,
        domain: str,
        target: Target,
        resolution: Resolution,
        company_source: CompanySource,
        campaign_id: str | None,
        actor: str,
    ) -> tuple[str, str | None]:
        name = target.company or resolution.company
        company = uow.companies.create(
            domain=domain, source=company_source, campaign_id=campaign_id, actor=actor
        )
        # Values the operator typed are recorded as theirs, so the engine cannot overwrite them.
        given: dict[str, Any] = {}
        if name and company_source is CompanySource.MANUAL:
            given["name"] = name
        code = country_code(target.country)
        if code:
            given["country_code"] = code
        if target.priority:
            given["priority"] = target.priority
        if given:
            uow.companies.update_fields(
                company.id, given, actor=actor, expected_version=company.row_version
            )
        if name and "name" not in given:
            uow.companies.update_fields(
                company.id, {"name": name}, actor=SYSTEM, expected_version=_version(uow, company.id)
            )
        uow.events.append(
            EntityType.COMPANY,
            company.id,
            "intake_accepted",
            actor,
            {"source": company_source.value},
        )

        note = self._add_person(uow, company.id, target, resolution, actor)
        if target.notes:
            uow.notes.add(company.id, target.notes, NoteSource.IMPORT, author=actor)
        return company.id, note

    def _add_person(
        self, uow: UnitOfWork, company_id: str, target: Target, resolution: Resolution, actor: str
    ) -> str | None:
        person = target.person or resolution.person
        title = target.title or resolution.title
        email = target.email.lower()
        email_domain = target.email_domain
        usable_email = bool(email) and email_domain is not None
        notes: list[str] = []
        if usable_email and is_free_mail(email_domain or "") and not self._allow_personal:
            usable_email = False
            notes.append("free-mail address ignored")
        if not (person or usable_email or target.linkedin_slug):
            return "; ".join(notes) or None

        name, _ = split_person(person) if person else ("", "")
        if person and not title:
            _, parsed_title = split_person(person)
            title = parsed_title
        first, last = split_name(name)
        linkedin = (
            f"https://www.linkedin.com/in/{target.linkedin_slug.lower()}"
            if target.linkedin_slug
            else None
        )
        contact = uow.contacts.add(
            company_id,
            rank=1,
            source=ContactSource.OPERATOR,
            full_name=name or None,
            first_name=first,
            last_name=last,
            title=title or None,
            linkedin_url=linkedin,
            status=ContactStatus.ACTIVE,
            actor=actor,
        )
        if usable_email:
            if uow.emails.by_address(email) is not None:
                notes.append("address already belongs to another contact")
            else:
                uow.emails.add(
                    contact.id, email, Provenance.OPERATOR_GIVEN, is_primary=True, actor=actor
                )
        return "; ".join(notes) or None

    def _merge(
        self,
        uow: UnitOfWork,
        company_id: str,
        name: str | None,
        existing_country: str | None,
        target: Target,
        actor: str,
    ) -> None:
        """A domain we already have: keep what exists, add notes, log values that differ."""
        if target.notes:
            uow.notes.add(company_id, target.notes, NoteSource.IMPORT, author=actor)
        offered_country = country_code(target.country)
        conflicts = {
            field_name: {"existing": current, "offered": offered}
            for field_name, current, offered in (
                ("name", name, target.company or None),
                ("country_code", existing_country, offered_country),
            )
            if offered and current and offered.lower() != str(current).lower()
        }
        uow.events.append(
            EntityType.COMPANY,
            company_id,
            "intake_merged",
            actor,
            {"conflicts": conflicts} if conflicts else {},
        )


def _version(uow: UnitOfWork, company_id: str) -> int:
    return uow.companies.get(company_id).row_version


# Pages that talk *about* a market (articles, reports, downloads) rather than a company's own
# product. The site behind them may still fit, but such hits crowd out real companies.
_CONTENT_PATH = re.compile(
    r"\.pdf$|/(blog|news|insights?|articles?|reports?|press|events?|webinars?|ebooks?|guides?)/",
    re.IGNORECASE,
)


def discovery_query(icp: str) -> str:
    """Phrase the campaign's description as a search for companies, not for articles about it."""
    return f"companies offering products or services for: {' '.join(icp.split())}"


def discover_rows(
    search: SearchProvider, queries: Iterable[str], *, per_query: int = 10
) -> list[dict[str, Any]]:
    """Candidate target rows from web searches, for ``discovery`` mode (website only).

    A hit's page title is not the company's name (it is often an article's headline), so no
    name is stored: research reads the name from the company's own site. Twice as many hits
    are asked for, articles and documents are skipped, and the page a company was found on is
    kept as a note.
    """
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for query in queries:
        found = 0
        for hit in search.search(query, max_results=per_query * 2):
            if found >= per_query:
                break
            domain = registrable_domain(hit.url)
            path = urlsplit(hit.url).path
            if (
                not domain
                or domain in seen
                or is_platform(domain)
                or is_free_mail(domain)
                or _CONTENT_PATH.search(path)
            ):
                continue
            seen.add(domain)
            found += 1
            rows.append({"website": domain, "notes": f"Found by discovery: {hit.url}"})
    return rows
