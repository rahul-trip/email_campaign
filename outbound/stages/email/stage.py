"""Stage 5: find and verify an address for the best contact; hold if the resolver is working.

Contacts are tried in rank order, up to ``MAX_CONTACTS``. The first with a safe address wins.
A catch-all sent to an asynchronous resolver holds the whole company (``catch_all_resolving``);
the tick job in ``poller.py`` releases it when the answer comes back, and this stage then runs
again and finds the resolved address.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from outbound.db.uow import UnitOfWork
from outbound.domain.directory import CONTRIBUTABLE, DIRECTORY
from outbound.domain.entities import Company, Contact, ContactEmail
from outbound.domain.enums import (
    WORKABLE_CONTACT_STATUSES,
    CompanyStatus,
    EmailStatus,
    FailureKind,
    HoldReason,
    Provenance,
)
from outbound.domain.names import display_name
from outbound.domain.policies import PolicyOutcome
from outbound.domain.ranking import can_be_written_to
from outbound.metering.metered import call_scope
from outbound.providers.ports import CatchAllResolver, EmailFinder, EmailVerifier
from outbound.stages.base import StageContext, StageFailure, StageResult, VendorUnavailable
from outbound.stages.contacts import operator_chosen
from outbound.stages.email.patterns import infer_pattern
from outbound.stages.email.waterfall import Record, Target, Verdict, Waterfall
from outbound.stages.policy import policy_decision_for

_CATCH_ALL = (
    EmailStatus.CATCH_ALL_PENDING,
    EmailStatus.CATCH_ALL_UNVERIFIED,
    EmailStatus.CATCH_ALL_RESOLVED,
)
MAX_CONTACTS = 3
POLL_DELAY = timedelta(hours=6)  # asynchronous resolvers answer in a day or three


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
    spends = True

    def __init__(self, deps: EmailDeps) -> None:
        self._waterfall = Waterfall(deps.finders, deps.verifier, deps.resolver)
        self._poll_delay = deps.poll_delay

    @staticmethod
    def _directory_pattern(ctx: StageContext, company: Company) -> str | None:
        """The directory's verified pattern, when this company has none of its own."""
        if company.skip_directory:
            return None
        return ctx.read(lambda uow: uow.directory.pattern(company.domain))

    @staticmethod
    def _may_guess(ctx: StageContext, company: Company, contact_id: str, catch_all: bool) -> bool:
        """Whether the commonest formats may be tried: the workspace allows it (setting
        ``guess_verified_addresses``, on by default), the domain is not known to accept
        everything, and the country's rule allows an address built from a company format."""
        if catch_all or not bool(ctx.workspace.settings.get("guess_verified_addresses", True)):
            return False
        decision = ctx.read(
            lambda uow: policy_decision_for(
                uow,
                company,
                stage=EmailStage.name,
                email_provenance=Provenance.PATTERN_INFERRED,
                recipient_id=contact_id,
            )
        )
        return decision.outcome is PolicyOutcome.ALLOW

    def handle(self, ctx: StageContext) -> StageResult:
        company = ctx.company
        people = ctx.read(
            lambda uow: [
                (c, uow.emails.for_contact(c.id))
                for c in uow.contacts.for_company(company.id)
                if c.status in WORKABLE_CONTACT_STATUSES
            ]
        )
        # An address held at this company that is a catch-all means every format would say the
        # same: guessing proves nothing there.
        catch_all_known = any(e.status in _CATCH_ALL for _, held in people for e in held if e.email)
        # "Find email again" on a person: only they are tried, with fresh vendor answers.
        asked = [(c, e) for c, e in people if c.refresh_email]
        if not asked:
            # Only people who can decide are written to: a decision-maker, or someone the
            # operator chose. The first three of a team page are not enough reason to spend money.
            wanted = ctx.campaign.target_titles if ctx.campaign else ()
            picked = ctx.read(lambda uow: operator_chosen(uow, [c for c, _ in people]))
            people = [
                (c, e) for c, e in people if can_be_written_to(c, wanted, picked, first_counts=True)
            ]
        if not (asked or people):
            raise StageFailure(
                "nobody at this lead is a decision-maker or was chosen: add the person you want"
                " to write to on the lead page, then retry",
                FailureKind.NO_PERSON,
            )
        people = (asked or people)[:MAX_CONTACTS]
        target = Target(
            allow_guesses=self._may_guess(ctx, company, people[0][0].id, catch_all_known),
            domain=company.domain,
            name=display_name(company.name, company.domain),
            pattern=company.email_pattern or self._directory_pattern(ctx, company),
            skip_finders=frozenset({DIRECTORY}) if company.skip_directory else frozenset(),
            site_emails=tuple((company.research or {}).get("site_emails", ())),
            safe_to_send_only=bool(ctx.workspace.settings.get("safe_to_send_only", True)),
            is_blocked=lambda address: ctx.read(lambda uow: uow.suppressions.blocks(address)),
        )

        records: list[Record] = []
        problems: list[str] = []
        unverified = False
        resolver_down = False
        chosen: Record | None = None
        chosen_contact: Contact | None = None
        pending = False
        reached = False
        finders_answered = checks_answered = checks_failed = 0
        for contact, emails in people:
            # Every paid call is recorded against the person it was for, so erasing the person
            # can find and clear it.
            with call_scope(contact_id=contact.id, fresh=contact.refresh_email):
                outcome = self._waterfall.run(contact, emails, target)
            records.extend(outcome.records)
            problems.extend(outcome.problems)
            unverified = unverified or outcome.catch_all_unverified
            resolver_down = resolver_down or outcome.resolver_down
            reached = reached or outcome.finders_reached
            finders_answered += outcome.finders_answered
            checks_answered += outcome.checks_answered
            checks_failed += outcome.checks_failed
            if outcome.verdict is Verdict.READY:
                chosen, chosen_contact = outcome.chosen, contact
                break
            if outcome.verdict is Verdict.PENDING:
                pending = True
                break

        def write(uow: UnitOfWork) -> None:
            _save(uow, records, chosen)
            for contact, _ in asked:  # they have been tried again
                uow.contacts.set_refresh_email(contact.id, False)
            if chosen is not None and chosen_contact is not None:
                _contribute(uow, company, chosen_contact, chosen, ctx.now)
                learned_here = _learn_pattern(company.email_pattern, chosen, chosen_contact)
                if learned_here:
                    uow.directory.observe_pattern(company.domain, learned_here, DIRECTORY, ctx.now)

        if chosen is not None and chosen_contact is not None:
            decision = ctx.read(
                lambda uow: policy_decision_for(
                    uow,
                    company,
                    stage=self.name,
                    email_provenance=chosen.provenance,
                    recipient_id=chosen_contact.id,
                )
            )
            if (
                decision.outcome is not PolicyOutcome.ALLOW
            ):  # a guessed Canadian address, or consent recorded for someone else
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
        if resolver_down and chosen is None:
            # Not "could not be proven": the check never happened. Failing sends the lead back
            # for another try on the next pass (up to the attempt limit), where holding it
            # would leave it for good.
            raise StageFailure(
                "a catch-all address was found but the catch-all resolver is not answering"
                f" ({'; '.join(problems[:2])}): it is tried again on the next pass"
            )
        if unverified and target.safe_to_send_only:
            return StageResult(
                CompanyStatus.HELD,
                reason="the only address found is on a catch-all domain and could not be proven",
                hold_reason=HoldReason.CATCH_ALL_UNVERIFIED,
                write=write,
            )
        detail = f" ({'; '.join(problems[:3])})" if problems else ""
        # Nobody could look (every finder out of credit, down or paused; or the verifier not
        # answering): that is not "no such address". The lead waits and is tried again by itself.
        if (reached and finders_answered == 0) or (checks_failed and not checks_answered):
            what = "email finder" if reached and finders_answered == 0 else "email verifier"
            raise VendorUnavailable(
                f"no {what} is answering{detail or ' (none is available)'}: the lead waits and"
                " is tried again by itself"
            )
        raise StageFailure(
            f"no valid email found for {len(people)} contact(s){detail}", FailureKind.NO_EMAIL
        )


def _contribute(
    uow: UnitOfWork, company: Company, contact: Contact, chosen: Record, now: datetime
) -> None:
    """Share a verified address with the directory. An address the operator typed in is not
    shared unless the workspace has opted in."""
    if chosen.status not in CONTRIBUTABLE or not (contact.first_name and contact.last_name):
        return
    if chosen.provenance is Provenance.OPERATOR_GIVEN and not bool(
        uow.workspace_settings().get("directory_share_operator_contacts", False)
    ):
        return
    uow.directory.observe_email(
        email=chosen.email,
        domain=company.domain,
        first_name=contact.first_name,
        last_name=contact.last_name,
        full_name=contact.full_name or f"{contact.first_name} {contact.last_name}",
        title=contact.title,
        provenance=chosen.provenance.value,
        source=chosen.found_by or chosen.provenance.value,
        verified_by=chosen.verified_by,
        observed_at=now,
    )


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
