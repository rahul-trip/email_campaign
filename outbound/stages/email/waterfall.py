"""Finding one address that is safe to send to, for one person.

Each candidate address is verified the moment it is found, because a finder's "found" is not
"deliverable". The order is cheapest first:

1. an address the operator gave (finders are skipped; it is still verified);
2. an address published on the company's own site that fits the person;
3. the company's learned pattern, one address only;
4. each finder in the configured order.

``valid`` stops the search. ``invalid`` or ``unknown`` moves on to the next finder. ``catch_all``
(the server accepts anything, so the mailbox is unproven) goes to the resolver and ends the
search for this person, since every other address at that domain would say the same.

The waterfall only decides; it writes nothing. It returns the addresses it learned about, and
the stage saves them with the status change.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from outbound.domain.entities import Contact, ContactEmail
from outbound.domain.enums import EmailStatus, Provenance
from outbound.domain.policies import is_sendable
from outbound.logging import get_logger
from outbound.providers.errors import ProviderError
from outbound.providers.ports import (
    CatchAllResolver,
    EmailFinder,
    EmailVerifier,
    PersonQuery,
    ResolutionStatus,
    VerificationStatus,
)
from outbound.stages.email.patterns import build_address, matches_person

log = get_logger(__name__)


class Verdict(StrEnum):
    READY = "ready"  # a safe address was found
    PENDING = "pending"  # the resolver is still working on a catch-all
    NONE = "none"  # nothing usable for this person


@dataclass
class Record:
    """An address the waterfall learned about, to be saved."""

    email: str
    provenance: Provenance
    status: EmailStatus
    found_by: str | None = None
    verified_by: str | None = None
    resolution_ref: str | None = None
    existing_id: str | None = None
    contact_id: str = ""


@dataclass
class Outcome:
    verdict: Verdict = Verdict.NONE
    records: list[Record] = field(default_factory=list)
    chosen: Record | None = None
    problems: list[str] = field(default_factory=list)
    catch_all_unverified: bool = False

    @property
    def pending(self) -> bool:
        return self.verdict is Verdict.PENDING


@dataclass(frozen=True)
class Target:
    """What the waterfall needs to know about the company."""

    domain: str
    name: str
    pattern: str | None = None
    site_emails: Sequence[str] = ()
    safe_to_send_only: bool = True
    # Finders left out for this company (the shared directory, when the lead skips it).
    skip_finders: frozenset[str] = frozenset()
    # True for an address that must never be contacted (the do-not-contact list). Checked
    # before an address is verified, so no money is spent on it and it is never chosen.
    is_blocked: Callable[[str], bool] = lambda address: False


class Waterfall:
    def __init__(
        self,
        finders: Sequence[EmailFinder],
        verifier: EmailVerifier,
        resolver: CatchAllResolver | None = None,
    ) -> None:
        self._finders = tuple(finders)
        self._verifier = verifier
        self._resolver = resolver

    def run(self, contact: Contact, emails: Sequence[ContactEmail], target: Target) -> Outcome:
        outcome = Outcome()
        tried: set[str] = set()
        blocked = target.is_blocked

        # Addresses we already hold for this person come first; none of them is retried if bad.
        for held in emails:
            if held.email:
                tried.add(held.email.lower())
            if self._reuse(held, contact, target, outcome):
                return outcome
        if outcome.pending:
            return outcome
        if any(e.provenance is Provenance.OPERATOR_GIVEN for e in emails):
            return outcome  # an operator-given address replaces the finders, even when bad

        first, last = contact.first_name or "", contact.last_name or ""
        if not (first and last):
            outcome.problems.append(
                f"{contact.full_name or 'a contact'} has no first and last name"
                " (edit the person on the lead page, or give their work email)"
            )
            return outcome

        candidates: list[tuple[str, Provenance, str | None]] = []
        for site in target.site_emails:
            if matches_person(site, first, last):
                candidates.append((site.lower(), Provenance.PUBLICLY_PUBLISHED, None))
                break
        if target.pattern:
            built = build_address(target.pattern, first, last, target.domain)
            if built:
                candidates.append((built, Provenance.PATTERN_INFERRED, None))

        for address, provenance, found_by in candidates:
            if address in tried or blocked(address):
                continue
            tried.add(address)
            if self._check(address, provenance, found_by, contact, outcome):
                return outcome
            if outcome.pending or outcome.catch_all_unverified:
                return outcome

        query = PersonQuery(
            first_name=first,
            last_name=last,
            company_name=target.name,
            linkedin_url=contact.linkedin_url,
        )
        for finder in self._finders:
            if finder.name in target.skip_finders:
                continue
            try:
                found = finder.find(query, target.domain)
            except ProviderError as error:
                outcome.problems.append(f"{finder.name}: {error}")
                continue
            if not found.email:
                continue
            address = found.email.lower()
            if address in tried or blocked(address):
                continue
            tried.add(address)
            provenance = (
                Provenance.PUBLICLY_PUBLISHED
                if address in {s.lower() for s in target.site_emails}
                else Provenance.API_DATABASE
            )
            if self._check(address, provenance, finder.name, contact, outcome):
                return outcome
            if outcome.pending or outcome.catch_all_unverified:
                return outcome
        return outcome

    # ------------------------------------------------------------------ helpers

    def _reuse(self, held: ContactEmail, contact: Contact, target: Target, out: Outcome) -> bool:
        """Use an address we already have. True when the search is over.

        An address the operator skipped verification for is used as it is: no verifier is
        called, whatever it said before (even ``invalid``). Suppression still wins.
        """
        if held.email is None:
            return False
        if held.status is EmailStatus.INVALID and not held.verification_skipped:
            return False
        if target.is_blocked(held.email):
            out.problems.append("an address we hold is on the do-not-contact list")
            return False
        if is_sendable(
            held.status,
            verification_skipped=held.verification_skipped,
            safe_to_send_only=target.safe_to_send_only,
        ):
            out.verdict = Verdict.READY
            out.chosen = Record(
                held.email,
                held.provenance,
                held.status,
                held.found_by,
                held.verified_by,
                held.resolution_ref,
                existing_id=held.id,
                contact_id=contact.id,
            )
            return True
        if held.status is EmailStatus.CATCH_ALL_PENDING:
            out.verdict = Verdict.PENDING
            return True
        if held.status is EmailStatus.CATCH_ALL_UNVERIFIED:
            out.catch_all_unverified = True
            return False
        if held.status is EmailStatus.UNVERIFIED:  # given by the operator, never checked
            return self._check(
                held.email, held.provenance, held.found_by, contact, out, existing_id=held.id
            )
        return False

    def _check(
        self,
        address: str,
        provenance: Provenance,
        found_by: str | None,
        contact: Contact,
        out: Outcome,
        *,
        existing_id: str | None = None,
    ) -> bool:
        """Verify one address. True when it is ready; sets the outcome for a catch-all."""
        try:
            checked = self._verifier.verify(address)
        except ProviderError as error:
            out.problems.append(f"{self._verifier.name}: {error}")
            return False
        verified_by = self._verifier.name

        def record(status: EmailStatus, ref: str | None = None) -> Record:
            made = Record(
                address,
                provenance,
                status,
                found_by,
                verified_by,
                ref,
                existing_id=existing_id,
                contact_id=contact.id,
            )
            out.records.append(made)
            return made

        if checked.status is VerificationStatus.VALID:
            out.chosen = record(EmailStatus.VALID)
            out.verdict = Verdict.READY
            return True
        if checked.status is VerificationStatus.INVALID:
            record(EmailStatus.INVALID)
            return False
        if checked.status is VerificationStatus.UNKNOWN:
            record(EmailStatus.UNKNOWN)
            return False
        return self._resolve(address, record, out)

    def _resolve(self, address: str, record: Callable[..., Record], out: Outcome) -> bool:
        if self._resolver is None:
            record(EmailStatus.CATCH_ALL_UNVERIFIED)
            out.catch_all_unverified = True
            return False
        try:
            ticket = self._resolver.submit(address)
        except ProviderError as error:
            out.problems.append(f"{self._resolver.name}: {error}")
            record(EmailStatus.CATCH_ALL_UNVERIFIED)
            out.catch_all_unverified = True
            return False
        if ticket.result is None:
            record(EmailStatus.CATCH_ALL_PENDING, ticket.ref)
            out.verdict = Verdict.PENDING
            return False
        if ticket.result.status is ResolutionStatus.VALID:
            out.chosen = record(EmailStatus.CATCH_ALL_RESOLVED)
            out.verdict = Verdict.READY
            return True
        if ticket.result.status is ResolutionStatus.INVALID:
            record(EmailStatus.INVALID)
            return False
        record(EmailStatus.CATCH_ALL_UNVERIFIED)
        out.catch_all_unverified = True
        return False
