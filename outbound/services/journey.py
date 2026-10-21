"""The story of one lead: how it arrived, and what happened at each stage since.

A pure function over data the lead service has already read, so it is easy to test and does
no I/O. The stages follow the company status path; what a stage "cost" is every vendor call made
between reaching the previous stage and reaching this one, which is when its work happened.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from outbound.db.repositories.imports import ImportOrigin
from outbound.domain.entities import (
    Campaign,
    Company,
    Contact,
    ContactEmail,
    Event,
    Message,
    ProviderCall,
)
from outbound.domain.enums import CompanySource, CompanyStatus, EntityType, ImportSource

S = CompanyStatus
# Each stage is finished when the lead reaches the status named here.
STAGES: tuple[tuple[str, str, tuple[CompanyStatus, ...]], ...] = (
    ("intake", "Intake", (S.NEW,)),
    ("research", "Research", (S.RESEARCHED,)),
    ("qualification", "Qualification", (S.QUALIFIED,)),
    ("people", "People", (S.CONTACTS_FOUND,)),
    ("email", "Email address", (S.EMAIL_READY,)),
    ("copy", "Copy", (S.COPY_READY,)),
    ("review", "Review", (S.APPROVED,)),
    ("outreach", "Draft and outreach", (S.IN_SEQUENCE, S.REPLIED, S.COMPLETED)),
)
_STOPPED = (S.DISQUALIFIED, S.REJECTED, S.SUPPRESSED)

_WAITING_FOR = {
    S.NEW: "The engine will research the company on the next run.",
    S.RESEARCHED: "The engine will check fit and the country policy on the next run.",
    S.QUALIFIED: "The engine will find the people to write to on the next run.",
    S.CONTACTS_FOUND: "The engine will find and verify an email address on the next run.",
    S.EMAIL_READY: "The engine will write the email on the next run.",
    S.COPY_READY: "Waiting for you: review the email and approve or reject it.",
    S.APPROVED: "Approved. The engine will place the email as a draft in the mailbox.",
    S.IN_SEQUENCE: "The first email is out. Follow-ups are not automatic yet.",
    S.REPLIED: "The person replied.",
    S.COMPLETED: "The sequence is finished.",
    S.REJECTED: "You rejected the email. Nothing more will happen unless you intervene.",
    S.SUPPRESSED: "On the do-not-contact list. Nothing more will happen.",
}


class StageState(StrEnum):
    DONE = "done"
    CURRENT = "current"  # the engine has work to do here
    WAITING = "waiting"  # it is the operator's turn
    HELD = "held"
    FAILED = "failed"
    STOPPED = "stopped"
    PENDING = "pending"


@dataclass(frozen=True)
class Fact:
    label: str
    value: str


@dataclass(frozen=True)
class CallView:
    at: datetime
    provider: str
    operation: str
    outcome: str
    cost_micro_usd: int


@dataclass(frozen=True)
class Incident:
    at: datetime
    text: str


@dataclass(frozen=True)
class StageView:
    key: str
    label: str
    state: StageState
    reached_at: datetime | None
    summary: str
    facts: list[Fact] = field(default_factory=list)
    incidents: list[Incident] = field(default_factory=list)
    calls: list[CallView] = field(default_factory=list)
    cost_micro_usd: int = 0


@dataclass(frozen=True)
class Origin:
    how: str
    at: datetime | None
    by: str | None
    facts: list[Fact]


@dataclass(frozen=True)
class Journey:
    company_id: str
    headline: str
    next_step: str
    origin: Origin
    stages: list[StageView]
    total_cost_micro_usd: int


@dataclass(frozen=True)
class JourneyData:
    company: Company
    campaign: Campaign | None
    origins: Sequence[ImportOrigin]
    people: Sequence[tuple[Contact, Sequence[ContactEmail]]]
    messages: Sequence[Message]
    events: Sequence[Event]
    calls: Sequence[ProviderCall]


def build_journey(data: JourneyData) -> Journey:
    company = data.company
    reached_at = _reached_times(data)
    furthest = _furthest(company.status, reached_at)

    stages: list[StageView] = []
    window_start: datetime | None = None
    blocked = False
    for index, (key, label, _) in enumerate(STAGES):
        reached = reached_at.get(index)
        if index <= furthest:
            state = StageState.DONE
        elif not blocked:
            state = _state_of_first_unfinished(company.status)
            blocked = True
        else:
            state = StageState.PENDING
        window_end = reached if state is StageState.DONE else None
        calls = _calls_between(data.calls, window_start, window_end, state)
        stages.append(
            StageView(
                key=key,
                label=label,
                state=state,
                reached_at=reached if state is StageState.DONE else None,
                summary="",
                calls=calls,
                cost_micro_usd=sum(c.cost_micro_usd for c in calls),
            )
        )
        if reached is not None and state is StageState.DONE:
            window_start = reached

    stages = [_describe(stage, data, window_start_of(stages, i)) for i, stage in enumerate(stages)]
    total = sum(c.cost_micro_usd for c in data.calls)
    return Journey(
        company_id=company.id,
        headline=_headline(company),
        next_step=_next_step(company),
        origin=_origin(data),
        stages=stages,
        total_cost_micro_usd=total,
    )


def window_start_of(stages: Sequence[StageView], index: int) -> datetime | None:
    """When the stage before this one was reached (the start of this stage's work)."""
    for earlier in reversed(stages[:index]):
        if earlier.reached_at is not None:
            return earlier.reached_at
    return None


# ------------------------------------------------------------------ progress


def _index_of(status: CompanyStatus) -> int | None:
    for index, (_, _, statuses) in enumerate(STAGES):
        if status in statuses:
            return index
    return None


def _reached_times(data: JourneyData) -> dict[int, datetime]:
    """When each stage was first completed, from the company's own status changes."""
    company = data.company
    times: dict[int, datetime] = {}
    if company.created_at is not None:
        times[0] = company.created_at
    for event in data.events:
        if event.entity_type is not EntityType.COMPANY:
            continue
        if event.type == "created":
            initial = _index_of(CompanyStatus(str(event.data.get("status", "new"))))
            if initial is not None:
                for index in range(initial + 1):
                    times.setdefault(index, event.created_at)
        elif event.type == "status_changed":
            moved_to = _index_of(CompanyStatus(str(event.data.get("to"))))
            if moved_to is not None:
                times.setdefault(moved_to, event.created_at)
    return times


def _furthest(status: CompanyStatus, reached_at: dict[int, datetime]) -> int:
    """The last finished stage. A lead sent back to an earlier status is shown there."""
    here = _index_of(status)
    if here is not None:
        return here
    return max(reached_at, default=0)


def _state_of_first_unfinished(status: CompanyStatus) -> StageState:
    if status is S.HELD:
        return StageState.HELD
    if status is S.FAILED:
        return StageState.FAILED
    if status in _STOPPED:
        return StageState.STOPPED
    if status is S.COPY_READY:
        return StageState.WAITING
    return StageState.CURRENT


def _calls_between(
    calls: Sequence[ProviderCall],
    start: datetime | None,
    end: datetime | None,
    state: StageState,
) -> list[CallView]:
    """Calls made after ``start`` and, for a finished stage, up to ``end``."""
    if state is StageState.PENDING:
        return []
    chosen = [
        c
        for c in calls
        if (start is None or c.created_at > start) and (end is None or c.created_at <= end)
    ]
    return [
        CallView(c.created_at, c.provider, c.operation, c.outcome.value, c.cost_micro_usd)
        for c in chosen
    ]


# ------------------------------------------------------------------ wording


def _name(company: Company) -> str:
    return company.name or company.domain


def _headline(company: Company) -> str:
    status = company.status
    if status is S.HELD and company.hold_reason:
        return f"Held: {company.hold_reason.value.replace('_', ' ')}"
    if status is S.FAILED:
        return f"Failed at {company.failed_stage or 'an unknown stage'}"
    return status.value.replace("_", " ").capitalize()


def _next_step(company: Company) -> str:
    status = company.status
    if status is S.HELD:
        return (
            "Held for you: open the lead, read why, and release it or leave it. A hold by a"
            " country rule can also be skipped for this lead from the stage that held it."
        )
    if status is S.FAILED:
        detail = f" ({company.last_error})" if company.last_error else ""
        return f"A stage failed{detail}. Retry it from the lead page."
    if status is S.DISQUALIFIED:
        return "Not a fit by the campaign's score. You can override and qualify it."
    return _WAITING_FOR.get(status, "")


_HOW = {
    CompanySource.MANUAL: "Added by an operator",
    CompanySource.DISCOVERY: "Found by the engine's search for companies",
    CompanySource.IMPORT: "Imported from a list",
    CompanySource.REFERRAL: "Came from a referral",
}
_VIA = {
    ImportSource.CSV: "a CSV file",
    ImportSource.XLSX: "an Excel file",
    ImportSource.CLI: "the command line",
    ImportSource.UI: "the web app",
    ImportSource.WEBHOOK: "the intake webhook",
    ImportSource.LEGACY_XLSX: "the legacy spreadsheet",
}


def _origin(data: JourneyData) -> Origin:
    company = data.company
    created = next(
        (e for e in data.events if e.entity_type is EntityType.COMPANY and e.type == "created"),
        None,
    )
    how = _HOW[company.source]
    if data.origins:
        how += f" via {_VIA[data.origins[0].source]}"
    facts = [Fact("Source", company.source.value)]
    if data.campaign:
        facts.append(Fact("Campaign", data.campaign.name))
    if company.manual_fields:
        facts.append(Fact("Set by an operator", _words(", ".join(company.manual_fields))))
    for origin in data.origins:
        row = origin.row
        place = origin.filename or _VIA[origin.source]
        # Only a file has meaningful row numbers; a quick-add always reads "row 2".
        in_file = origin.source in {ImportSource.CSV, ImportSource.XLSX, ImportSource.LEGACY_XLSX}
        where = f"{place}, row {row.row_number}" if row.row_number and in_file else place
        facts.append(Fact("Input", where))
        supplied = ", ".join(f"{k}: {v}" for k, v in row.raw.items() if v not in (None, ""))
        if supplied:
            facts.append(Fact("As supplied", supplied))
        found = f"matched on {row.anchor.value.replace('_', ' ')}"
        if row.resolved_domain:
            confidence = (
                f", {round(row.resolution_confidence * 100)}% sure"
                if row.resolution_confidence is not None
                else ""
            )
            found += f"; website {row.resolved_domain}{confidence}"
        facts.append(Fact("Matching", found))
        if row.reason:
            facts.append(Fact("Note", row.reason))
    return Origin(
        how=how,
        at=created.created_at if created else company.created_at,
        by=created.actor if created else None,
        facts=facts,
    )


# ------------------------------------------------------------------ stage details


def _describe(stage: StageView, data: JourneyData, since: datetime | None) -> StageView:
    describe = _DESCRIBERS[stage.key]
    facts, summary = describe(data, stage)
    return StageView(
        key=stage.key,
        label=stage.label,
        state=stage.state,
        reached_at=stage.reached_at,
        summary=summary or _default_summary(stage, data.company),
        facts=facts,
        incidents=_incidents(data, since, stage.reached_at, stage.state),
        calls=stage.calls,
        cost_micro_usd=stage.cost_micro_usd,
    )


def _default_summary(stage: StageView, company: Company) -> str:
    match stage.state:
        case StageState.DONE:
            return "Done."
        case StageState.HELD:
            return (
                f"Held: {company.hold_reason.value.replace('_', ' ')}"
                if company.hold_reason
                else "Held."
            )
        case StageState.FAILED:
            return f"Failed: {company.last_error}" if company.last_error else "Failed."
        case StageState.STOPPED:
            return f"Stopped: the lead is {company.status.value.replace('_', ' ')}."
        case StageState.WAITING:
            return "Waiting for you."
        case StageState.CURRENT:
            return "Next up."
        case StageState.PENDING:
            return "Not reached yet."


def _incidents(
    data: JourneyData, start: datetime | None, end: datetime | None, state: StageState
) -> list[Incident]:
    """Holds, failures and overrides during the stage, from the company's history."""
    if state is StageState.PENDING:
        return []
    found: list[Incident] = []
    for event in data.events:
        if event.entity_type is not EntityType.COMPANY or event.type != "status_changed":
            continue
        if (start is not None and event.created_at <= start) or (
            end is not None and event.created_at > end
        ):
            continue
        to = str(event.data.get("to"))
        if to not in {S.HELD, S.FAILED, S.DISQUALIFIED, S.REJECTED, S.SUPPRESSED} and not (
            event.actor.startswith("user:") and event.data.get("from") in {S.HELD, S.FAILED}
        ):
            continue
        text = f"{str(event.data.get('from')).replace('_', ' ')} to {to.replace('_', ' ')}"
        extra = event.data.get("hold_reason") or event.data.get("error") or event.data.get("reason")
        if extra:
            text += f": {str(extra).replace('_', ' ')}"
        found.append(Incident(event.created_at, f"{text} ({event.actor})"))
    return found


def _intake(data: JourneyData, stage: StageView) -> tuple[list[Fact], str]:
    company = data.company
    facts = [Fact("Domain", company.domain), Fact("Name", company.name or "(not given)")]
    facts.append(Fact("Country", company.country_code or "(not known yet)"))
    facts.append(Fact("Priority", str(company.priority)))
    return facts, f"{_name(company)} entered the pipeline."


def _research(data: JourneyData, stage: StageView) -> tuple[list[Fact], str]:
    research: dict[str, Any] = data.company.research or {}
    if not research:
        return [], ""
    facts: list[Fact] = []
    if research.get("summary"):
        facts.append(Fact("What they do", str(research["summary"])))
    for label, key in (("Products", "products"), ("In the news", "news"), ("Hooks", "hooks")):
        if research.get(key):
            facts.append(Fact(label, _joined(research[key])))
    for label, key in (("Hiring", "hiring"), ("Technology", "tech")):
        if research.get(key):
            facts.append(Fact(label, _joined(research[key])))
    pages = research.get("pages") or []
    facts.append(Fact("Pages read", str(len(pages))))
    if research.get("site_emails"):
        facts.append(Fact("Addresses on the site", _joined(research["site_emails"])))
    if research.get("country_evidence"):
        facts.append(Fact("Country evidence", str(research["country_evidence"])))
    if research.get("legal_evidence"):
        facts.append(Fact("Legal-entity evidence", str(research["legal_evidence"])))
    answers = data.company.research_answers or {}
    for question, answer in answers.items():
        facts.append(Fact(str(question), _joined(answer)))
    thin = " The site gave little to go on." if research.get("thin") else ""
    return facts, f"Read {len(pages)} pages.{thin}"


def _qualification(data: JourneyData, stage: StageView) -> tuple[list[Fact], str]:
    company = data.company
    facts: list[Fact] = []
    if company.fit_score is not None:
        needed = f" (minimum {data.campaign.min_fit_score})" if data.campaign else ""
        facts.append(Fact("Fit score", f"{company.fit_score}{needed}"))
    if company.fit_reason:
        facts.append(Fact("Why", company.fit_reason))
    facts.append(Fact("Country", company.country_code or "unknown"))
    facts.append(Fact("Legal entity", company.legal_entity_type.value.replace("_", " ")))
    suggestion = (company.research or {}).get("country_suggestion")
    if suggestion:
        facts.append(
            Fact("Suggested country", f"{suggestion.get('code')} ({suggestion.get('evidence')})")
        )
    if company.policy_skip_from:
        facts.append(
            Fact(
                "Country policy",
                f"skipped by the operator from the {company.policy_skip_from.value} step on",
            )
        )
    decision = company.policy_decision or {}
    if decision:
        outcome = str(decision.get("outcome", "")).replace("_", " ")
        rule = str(decision.get("rule") or "").replace("_", " ")
        facts.append(Fact("Country policy", f"{outcome}" + (f" ({rule})" if rule else "")))
        for reason in decision.get("reasons") or []:
            facts.append(Fact("Policy note", str(reason)))
    if company.fit_score is None:
        return facts, ""
    return facts, f"Fit {company.fit_score}."


def _people(data: JourneyData, stage: StageView) -> tuple[list[Fact], str]:
    facts = [
        Fact(
            f"#{contact.rank}",
            f"{contact.full_name or '(no name)'}"
            + (f", {contact.title}" if contact.title else "")
            + f" ({contact.source.value.replace('_', ' ')}, {contact.status.value})",
        )
        for contact, _ in data.people
    ]
    return (
        facts,
        f"{len(data.people)} {'person' if len(data.people) == 1 else 'people'}." if facts else "",
    )


def _email(data: JourneyData, stage: StageView) -> tuple[list[Fact], str]:
    facts: list[Fact] = []
    best: ContactEmail | None = None
    for contact, emails in data.people:
        who = contact.full_name or "(no name)"
        for email in emails:
            how = email.provenance.value.replace("_", " ")
            if email.found_by:
                how += f", found by {email.found_by}"
            if email.verified_by:
                how += f", checked by {email.verified_by}"
            marker = " (primary)" if email.is_primary else ""
            facts.append(
                Fact(
                    who,
                    f"{email.email or '(erased)'} is {_words(email.status.value)}{marker}; {how}",
                )
            )
            if email.is_primary and best is None:
                best = email
    if data.company.email_pattern:
        facts.append(Fact("Address pattern", data.company.email_pattern))
    summary = f"Using an address that is {best.status.value.replace('_', ' ')}." if best else ""
    return facts, summary


def _copy(data: JourneyData, stage: StageView) -> tuple[list[Fact], str]:
    facts: list[Fact] = []
    for message in data.messages:
        label = f"Touch {message.step + 1}"
        facts.append(Fact(label, f"{message.subject} ({message.state.value})"))
        report = message.lint_report or {}
        if report:
            issues = [str(i.get("message")) for i in report.get("issues") or []]
            checks = (
                f"{report.get('word_count')} words, reading grade {report.get('reading_grade')}"
            )
            facts.append(
                Fact(
                    f"{label} checks",
                    checks + (f"; flagged: {'; '.join(issues)}" if issues else "; clean"),
                )
            )
    return facts, f"{len(data.messages)} written." if data.messages else ""


def _review(data: JourneyData, stage: StageView) -> tuple[list[Fact], str]:
    facts: list[Fact] = []
    for message in data.messages:
        label = f"Touch {message.step + 1}"
        facts.append(Fact(label, message.state.value))
        if message.edit_distance is not None:
            facts.append(
                Fact(f"{label} edited", f"{round(message.edit_distance * 100)}% changed by you")
            )
    for event in data.events:
        if event.entity_type is EntityType.MESSAGE and event.type == "status_changed":
            to = str(event.data.get("to"))
            if to in {"approved", "rejected"}:
                facts.append(
                    Fact(to.capitalize(), f"{event.created_at:%Y-%m-%d %H:%M} by {event.actor}")
                )
    return facts, ""


def _outreach(data: JourneyData, stage: StageView) -> tuple[list[Fact], str]:
    facts: list[Fact] = []
    for message in data.messages:
        label = f"Touch {message.step + 1}"
        if message.state.value in {"drafted", "sent", "bounced"}:
            facts.append(Fact(label, message.state.value))
        if message.remote_draft_id:
            facts.append(Fact(f"{label} draft", "saved in the mailbox"))
        if message.sent_at:
            facts.append(Fact(f"{label} sent", f"{message.sent_at:%Y-%m-%d %H:%M}"))
    return facts, ""


def _words(text: str) -> str:
    return text.replace("_", " ")


def _joined(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return "; ".join(str(v) for v in value)
    return str(value)


_DESCRIBERS = {
    "intake": _intake,
    "research": _research,
    "qualification": _qualification,
    "people": _people,
    "email": _email,
    "copy": _copy,
    "review": _review,
    "outreach": _outreach,
}
