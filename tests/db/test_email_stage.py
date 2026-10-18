"""Stage 5 under the runner, and the tick job that collects catch-all answers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.entities import Company, CountryPolicy
from outbound.domain.enums import (
    CompanySource,
    CompanyStatus,
    ContactSource,
    EmailStatus,
    HoldReason,
    PolicyRule,
    Provenance,
)
from outbound.domain.policy_seeds import DEFAULT_COUNTRY_POLICIES
from outbound.providers.ports import (
    FinderResult,
    PersonQuery,
    ResolutionResult,
    ResolutionStatus,
    ResolutionTicket,
    VerificationResult,
    VerificationStatus,
)
from outbound.runner.guards import Guards
from outbound.runner.runner import Runner
from outbound.stages.email.poller import CatchAllPoller
from outbound.stages.email.stage import EmailDeps, EmailStage

C = CompanyStatus
V = VerificationStatus
NOW = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)


class Finder:
    def __init__(self, name: str, answers: dict[str, str | None]) -> None:
        self.name = name
        self.answers = answers  # last name -> address
        self.calls: list[str] = []

    def find(self, person: PersonQuery, domain: str) -> FinderResult:
        self.calls.append(person.last_name)
        return FinderResult(email=self.answers.get(person.last_name), provider=self.name)


class Verifier:
    name = "verifier"

    def __init__(self, answers: dict[str, VerificationStatus]) -> None:
        self.answers = answers
        self.checked: list[str] = []

    def verify(self, email: str) -> VerificationResult:
        self.checked.append(email)
        return VerificationResult(
            email=email, status=self.answers.get(email, V.INVALID), provider=self.name
        )


class Resolver:
    """Asynchronous: submit leaves a ticket; ``answer`` is what a later poll returns."""

    name = "resolver"

    def __init__(self, answer: ResolutionStatus | None = None) -> None:
        self.answer = answer
        self.submitted: list[str] = []
        self.polls = 0

    def submit(self, email: str) -> ResolutionTicket:
        self.submitted.append(email)
        return ResolutionTicket(ref="job-1", email=email, provider=self.name)

    def poll(self, ticket: ResolutionTicket) -> ResolutionResult | None:
        self.polls += 1
        if self.answer is None:
            return None
        return ResolutionResult(email=ticket.email, status=self.answer, provider=self.name)


def seed(factory: UnitOfWorkFactory, ws: str) -> None:
    with factory(ws) as uow:
        for policy in DEFAULT_COUNTRY_POLICIES:
            uow.policies.add_if_missing(policy)
        uow.policies.add_if_missing(CountryPolicy("ZA", PolicyRule.ALLOW_WITH_FOOTER))
        uow.commit()


def lead(
    factory: UnitOfWorkFactory,
    ws: str,
    people: list[tuple[str, str]],
    *,
    country: str = "US",
    domain: str = "acme.com",
    site_emails: list[str] | None = None,
) -> str:
    """A company at ``contacts_found`` with ranked contacts given as (first, last)."""
    seed(factory, ws)
    with factory(ws) as uow:
        company = uow.companies.create(
            domain=domain, source=CompanySource.MANUAL, country_code=country, name="Acme"
        )
        company = uow.companies.update_fields(
            company.id,
            {"research": {"site_emails": site_emails or []}},
            actor="system",
            expected_version=company.row_version,
        )
        version = company.row_version
        for step in (C.RESEARCHED, C.QUALIFIED, C.CONTACTS_FOUND):
            version = uow.companies.transition(
                company.id, step, expected_version=version
            ).row_version
        for rank, (first, last) in enumerate(people, start=1):
            uow.contacts.add(
                company.id,
                rank=rank,
                source=ContactSource.SITE,
                full_name=f"{first} {last}",
                first_name=first,
                last_name=last,
            )
        uow.commit()
        return company.id


def run_stage(
    factory: UnitOfWorkFactory,
    ws: str,
    finders: list[Finder],
    verifier: Verifier,
    resolver: Resolver | None = None,
) -> None:
    stage = EmailStage(EmailDeps(finders, verifier, resolver))
    Runner(factory, ws, [stage], Guards(), now=lambda: NOW).run_pipeline()


def company(factory: UnitOfWorkFactory, ws: str, company_id: str) -> Company:
    with factory(ws) as uow:
        return uow.companies.get(company_id)


def addresses(factory: UnitOfWorkFactory, ws: str, company_id: str) -> dict[str, EmailStatus]:
    with factory(ws) as uow:
        return {
            a.email or "": a.status
            for c in uow.contacts.for_company(company_id)
            for a in uow.emails.for_contact(c.id)
        }


# ------------------------------------------------------------------ the stage


def test_a_verified_address_is_saved_as_primary_and_the_company_moves_on(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = lead(factory, ws, [("Jane", "Doe")])
    run_stage(
        factory,
        ws,
        [Finder("hunter", {"Doe": "jane.doe@acme.com"})],
        Verifier({"jane.doe@acme.com": V.VALID}),
    )
    after = company(factory, ws, cid)
    assert after.status is C.EMAIL_READY
    assert after.email_pattern == "{first}.{last}"
    with factory(ws) as uow:
        [contact] = uow.contacts.for_company(cid)
        [address] = uow.emails.for_contact(contact.id)
    assert (address.email, address.status, address.is_primary) == (
        "jane.doe@acme.com",
        EmailStatus.VALID,
        True,
    )
    assert (address.provenance, address.found_by, address.verified_by) == (
        Provenance.API_DATABASE,
        "hunter",
        "verifier",
    )
    assert address.verified_at is not None


def test_the_next_contact_is_tried_when_the_first_has_no_valid_address(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = lead(factory, ws, [("Jane", "Doe"), ("Sam", "Lee")])
    finder = Finder("hunter", {"Doe": "wrong@acme.com", "Lee": "sam.lee@acme.com"})
    verifier = Verifier({"sam.lee@acme.com": V.VALID})
    run_stage(factory, ws, [finder], verifier)
    assert company(factory, ws, cid).status is C.EMAIL_READY
    assert addresses(factory, ws, cid) == {
        "wrong@acme.com": EmailStatus.INVALID,
        "sam.lee@acme.com": EmailStatus.VALID,
    }


def test_a_learned_pattern_means_one_check_and_no_finder_call(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = lead(factory, ws, [("Sam", "Lee")])
    with factory(ws) as uow:
        row = uow.companies.get(cid)
        uow.companies.update_fields(
            cid,
            {"email_pattern": "{first}.{last}"},
            actor="system",
            expected_version=row.row_version,
        )
        uow.commit()
    finder = Finder("hunter", {"Lee": "never-asked@acme.com"})
    verifier = Verifier({"sam.lee@acme.com": V.VALID})
    run_stage(factory, ws, [finder], verifier)
    assert (finder.calls, verifier.checked) == ([], ["sam.lee@acme.com"])
    assert company(factory, ws, cid).status is C.EMAIL_READY
    with factory(ws) as uow:
        [contact] = uow.contacts.for_company(cid)
        [address] = uow.emails.for_contact(contact.id)
    assert address.provenance is Provenance.PATTERN_INFERRED


def test_when_every_finder_misses_the_lead_fails_with_a_reason(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = lead(factory, ws, [("Jane", "Doe")])
    run_stage(factory, ws, [Finder("hunter", {})], Verifier({}))
    after = company(factory, ws, cid)
    assert (after.status, after.failed_stage) == (C.FAILED, "email")
    assert "no valid email found" in (after.last_error or "")


def test_at_most_three_contacts_are_tried(factory: UnitOfWorkFactory, ws: str) -> None:
    cid = lead(factory, ws, [("A", "One"), ("B", "Two"), ("C", "Three"), ("D", "Four")])
    finder = Finder("hunter", {})
    run_stage(factory, ws, [finder], Verifier({}))
    assert finder.calls == ["One", "Two", "Three"]
    assert company(factory, ws, cid).status is C.FAILED


def test_a_published_address_that_fits_the_person_is_used_before_a_paid_finder(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = lead(factory, ws, [("Jane", "Doe")], site_emails=["jane.doe@acme.com"])
    finder = Finder("hunter", {"Doe": "other@acme.com"})
    run_stage(factory, ws, [finder], Verifier({"jane.doe@acme.com": V.VALID}))
    assert finder.calls == []
    with factory(ws) as uow:
        [contact] = uow.contacts.for_company(cid)
        [address] = uow.emails.for_contact(contact.id)
    assert address.provenance is Provenance.PUBLICLY_PUBLISHED


def test_an_operator_address_is_verified_and_kept_with_its_provenance(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = lead(factory, ws, [("Jane", "Doe")])
    with factory(ws) as uow:
        [contact] = uow.contacts.for_company(cid)
        uow.emails.add(contact.id, "jane@acme.com", Provenance.OPERATOR_GIVEN, is_primary=True)
        uow.commit()
    finder = Finder("hunter", {"Doe": "x@acme.com"})
    run_stage(factory, ws, [finder], Verifier({"jane@acme.com": V.VALID}))
    assert company(factory, ws, cid).status is C.EMAIL_READY
    assert finder.calls == []
    assert addresses(factory, ws, cid) == {"jane@acme.com": EmailStatus.VALID}


def test_a_guessed_canadian_address_is_held_by_policy(factory: UnitOfWorkFactory, ws: str) -> None:
    cid = lead(factory, ws, [("Jane", "Doe")], country="CA")
    with factory(ws) as uow:
        company_row = uow.companies.get(cid)
        uow.companies.update_fields(
            cid,
            {"email_pattern": "{first}.{last}"},
            actor="system",
            expected_version=company_row.row_version,
        )
        uow.commit()
    run_stage(factory, ws, [Finder("hunter", {})], Verifier({"jane.doe@acme.com": V.VALID}))
    after = company(factory, ws, cid)
    assert (after.status, after.hold_reason) == (C.HELD, HoldReason.CONSENT_REQUIRED)
    assert addresses(factory, ws, cid) == {"jane.doe@acme.com": EmailStatus.VALID}


def test_a_catch_all_without_a_resolver_holds_the_lead_as_unverified(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid = lead(factory, ws, [("Jane", "Doe")])
    run_stage(
        factory,
        ws,
        [Finder("hunter", {"Doe": "jane.doe@acme.com"})],
        Verifier({"jane.doe@acme.com": V.CATCH_ALL}),
    )
    after = company(factory, ws, cid)
    assert (after.status, after.hold_reason) == (C.HELD, HoldReason.CATCH_ALL_UNVERIFIED)


# ------------------------------------------------------------------ asynchronous catch-all


def hold_on_catch_all(factory: UnitOfWorkFactory, ws: str) -> tuple[str, Resolver]:
    cid = lead(factory, ws, [("Jane", "Doe")])
    resolver = Resolver()
    run_stage(
        factory,
        ws,
        [Finder("hunter", {"Doe": "jane.doe@acme.com"})],
        Verifier({"jane.doe@acme.com": V.CATCH_ALL}),
        resolver,
    )
    return cid, resolver


def test_an_asynchronous_resolver_holds_the_company_until_a_wake_up_time(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid, resolver = hold_on_catch_all(factory, ws)
    after = company(factory, ws, cid)
    assert (after.status, after.hold_reason) == (C.HELD, HoldReason.CATCH_ALL_RESOLVING)
    assert after.next_action_at == NOW + timedelta(hours=6)
    assert addresses(factory, ws, cid) == {"jane.doe@acme.com": EmailStatus.CATCH_ALL_PENDING}
    assert resolver.submitted == ["jane.doe@acme.com"]


def poller(factory: UnitOfWorkFactory, ws: str, resolver: Resolver, at: datetime) -> CatchAllPoller:
    return CatchAllPoller(factory, ws, resolver, now=lambda: at)


def test_the_poller_does_nothing_before_the_wake_up_time(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid, resolver = hold_on_catch_all(factory, ws)
    counts = poller(factory, ws, resolver, NOW + timedelta(hours=1)).run()
    assert counts["checked"] == 0 and resolver.polls == 0
    assert company(factory, ws, cid).status is C.HELD


def test_no_answer_yet_reschedules_the_next_look(factory: UnitOfWorkFactory, ws: str) -> None:
    cid, resolver = hold_on_catch_all(factory, ws)
    later = NOW + timedelta(hours=7)
    counts = poller(factory, ws, resolver, later).run()
    assert (counts["checked"], counts["still_waiting"]) == (1, 1)
    after = company(factory, ws, cid)
    assert (after.status, after.next_action_at) == (C.HELD, later + timedelta(hours=6))


def test_a_valid_answer_releases_the_company_and_the_stage_then_finishes(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid, resolver = hold_on_catch_all(factory, ws)
    resolver.answer = ResolutionStatus.VALID
    counts = poller(factory, ws, resolver, NOW + timedelta(hours=7)).run()
    assert counts["released"] == 1
    assert company(factory, ws, cid).status is C.CONTACTS_FOUND
    assert addresses(factory, ws, cid) == {"jane.doe@acme.com": EmailStatus.CATCH_ALL_RESOLVED}

    verifier = Verifier({})
    run_stage(factory, ws, [Finder("hunter", {})], verifier, resolver)
    assert company(factory, ws, cid).status is C.EMAIL_READY
    assert verifier.checked == []  # the resolved address needs no second check
    with factory(ws) as uow:
        [contact] = uow.contacts.for_company(cid)
        assert uow.emails.for_contact(contact.id)[0].is_primary


def test_an_invalid_answer_releases_the_company_to_try_the_next_contact(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid, resolver = hold_on_catch_all(factory, ws)
    resolver.answer = ResolutionStatus.INVALID
    poller(factory, ws, resolver, NOW + timedelta(hours=7)).run()
    assert addresses(factory, ws, cid) == {"jane.doe@acme.com": EmailStatus.INVALID}
    assert company(factory, ws, cid).status is C.CONTACTS_FOUND
    run_stage(factory, ws, [Finder("hunter", {})], Verifier({}), resolver)
    assert company(factory, ws, cid).status is C.FAILED  # nobody else to try


def test_an_undecided_answer_leaves_the_address_unverified_and_holds_again(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid, resolver = hold_on_catch_all(factory, ws)
    resolver.answer = ResolutionStatus.UNRESOLVED
    poller(factory, ws, resolver, NOW + timedelta(hours=7)).run()
    run_stage(factory, ws, [Finder("hunter", {})], Verifier({}), resolver)
    after = company(factory, ws, cid)
    assert (after.status, after.hold_reason) == (C.HELD, HoldReason.CATCH_ALL_UNVERIFIED)


def test_a_company_released_by_hand_is_not_touched_by_the_poller(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    cid, resolver = hold_on_catch_all(factory, ws)
    with factory(ws) as uow:
        current = uow.companies.get(cid)
        uow.companies.transition(
            cid, C.CONTACTS_FOUND, expected_version=current.row_version, actor="operator"
        )
        uow.commit()
    counts = poller(factory, ws, resolver, NOW + timedelta(hours=7)).run()
    assert counts["checked"] == 0
