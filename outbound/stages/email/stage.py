"""Stage 5: find and verify an address for the best contact; hold if the resolver is working.

Contacts are tried in rank order, up to ``MAX_CONTACTS``. The first with a safe address wins.
A catch-all sent to an asynchronous resolver holds the whole company (``catch_all_resolving``);
the tick job in ``poller.py`` releases it when the answer comes back, and this stage then runs
again and finds the resolved address.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from outbound.db.uow import UnitOfWork
from outbound.domain.entities import Contact, ContactEmail
from outbound.domain.enums import CompanyStatus, ContactStatus, EmailStatus, HoldReason
from outbound.domain.policies import PolicyOutcome
from outbound.providers.metered import call_scope
from outbound.providers.ports import CatchAllResolver, EmailFinder, EmailVerifier
from outbound.stages.base import StageContext, StageFailure, StageResult
from outbound.stages.email.patterns import infer_pattern
from outbound.stages.email.waterfall import Record, Target, Verdict, Waterfall
from outbound.stages.policy import policy_decision_for

MAX_CONTACTS = 3
POLL_DELAY = timedelta(hours=6)  # asynchronous resolvers answer in a day or three
_USABLE = (ContactStatus.CANDIDATE, ContactStatus.ACTIVE)


@dataclass(frozen=True)
class EmailDeps:
    finders: Sequence[EmailFinder]
    verifier: EmailVerifier
    resolver: CatchAllResolver | None = None
    poll_delay: timedelta = POLL_DELAY


class EmailStage:
    name = "email"
    input_status = CompanyStatus.CONTACTS_FOUND
    guard_policy = True

    def __init__(self, deps: EmailDeps) -> None:
        self._waterfall = Waterfall(deps.finders, deps.verifier, deps.resolver)
        self._poll_delay = deps.poll_delay

    def handle(self, ctx: StageContext) -> StageResult:
        company = ctx.company
        people = ctx.read(
            lambda uow: [
                (c, uow.emails.for_contact(c.id))
                for c in uow.contacts.for_company(company.id)
                if c.status in _USABLE
            ]
        )[:MAX_CONTACTS]
        target = Target(
            domain=company.domain,
            name=company.name or company.domain.split(".")[0].title(),
            pattern=company.email_pattern,
            site_emails=tuple((company.research or {}).get("site_emails", ())),
            safe_to_send_only=bool(ctx.workspace.settings.get("safe_to_send_only", True)),
        )

        records: list[Record] = []
        problems: list[str] = []
        unverified = False
        chosen: Record | None = None
        chosen_contact: Contact | None = None
        pending = False
        for contact, emails in people:
            # Every paid call is recorded against the person it was for, so erasing the person
            # can find and clear it.
            with call_scope(contact_id=contact.id):
                outcome = self._waterfall.run(contact, emails, target)
            records.extend(outcome.records)
            problems.extend(outcome.problems)
            unverified = unverified or outcome.catch_all_unverified
            if outcome.verdict is Verdict.READY:
                chosen, chosen_contact = outcome.chosen, contact
                break
            if outcome.verdict is Verdict.PENDING:
                pending = True
                break

        def write(uow: UnitOfWork) -> None:
            _save(uow, records, chosen)

        if chosen is not None and chosen_contact is not None:
            decision = ctx.read(
                lambda uow: policy_decision_for(uow, company, email_provenance=chosen.provenance)
            )
            if (
                decision.outcome is not PolicyOutcome.ALLOW
            ):  # for example a guessed Canadian address
                return StageResult(
                    CompanyStatus.HELD,
                    reason="; ".join(decision.reasons),
                    hold_reason=decision.hold_reason or HoldReason.NEEDS_OPERATOR,
                    company_updates={"policy_decision": decision.to_json()},
                    write=write,
                )
            updates: dict[str, Any] = {}
            learned = _learn_pattern(company.email_pattern, chosen, chosen_contact)
            if learned:
                updates["email_pattern"] = learned
            return StageResult(
                CompanyStatus.EMAIL_READY,
                reason=f"address chosen ({chosen.status.value})",
                company_updates=updates,
                write=write,
            )
        if pending:
            return StageResult(
                CompanyStatus.HELD,
                reason="a catch-all address is being resolved",
                hold_reason=HoldReason.CATCH_ALL_RESOLVING,
                next_action_at=ctx.now + self._poll_delay,
                write=write,
            )
        if unverified and target.safe_to_send_only:
            return StageResult(
                CompanyStatus.HELD,
                reason="the only address found is on a catch-all domain and could not be proven",
                hold_reason=HoldReason.CATCH_ALL_UNVERIFIED,
                write=write,
            )
        detail = f" ({'; '.join(problems[:3])})" if problems else ""
        raise StageFailure(f"no valid email found for {len(people)} contact(s){detail}")


def _learn_pattern(known: str | None, chosen: Record, contact: Contact) -> str | None:
    if known or chosen.status is not EmailStatus.VALID:
        return None
    if not (contact.first_name and contact.last_name):
        return None
    return infer_pattern(chosen.email, contact.first_name, contact.last_name)


def _save(uow: UnitOfWork, records: Sequence[Record], chosen: Record | None) -> None:
    chosen_id: str | None = None
    for record in records:
        saved = _save_one(uow, record)
        if record is chosen and saved is not None:
            chosen_id = saved.id
    if chosen is not None and chosen_id is None and chosen.existing_id:
        chosen_id = chosen.existing_id
    if chosen_id is not None:
        uow.emails.set_primary(chosen_id)


def _save_one(uow: UnitOfWork, record: Record) -> ContactEmail | None:
    if record.existing_id:
        current = uow.emails.get(record.existing_id)
        if current.status is record.status:
            return current
        return uow.emails.transition(
            record.existing_id,
            record.status,
            verified_by=record.verified_by,
            resolution_ref=record.resolution_ref,
        )
    if uow.emails.by_address(record.email) is not None:
        return None  # already belongs to someone; the unique address rule keeps one owner
    return uow.emails.add(
        record.contact_id,
        record.email,
        record.provenance,
        found_by=record.found_by,
        status=record.status,
        verified_by=record.verified_by,
        resolution_ref=record.resolution_ref,
    )
