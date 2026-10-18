"""The email waterfall: order, inline verification, catch-all handling and provenance."""

from __future__ import annotations

from outbound.domain.entities import Contact, ContactEmail
from outbound.domain.enums import ContactSource, ContactStatus, EmailStatus, Provenance
from outbound.providers.errors import ProviderError
from outbound.providers.ports import (
    FinderResult,
    PersonQuery,
    ResolutionResult,
    ResolutionStatus,
    ResolutionTicket,
    VerificationResult,
    VerificationStatus,
)
from outbound.stages.email.waterfall import Outcome, Target, Verdict, Waterfall

V = VerificationStatus
E = EmailStatus


class FakeFinder:
    def __init__(self, name: str, answer: str | None = None, *, fail: bool = False) -> None:
        self.name = name
        self.answer = answer
        self.fail = fail
        self.calls = 0

    def find(self, person: PersonQuery, domain: str) -> FinderResult:
        self.calls += 1
        if self.fail:
            raise ProviderError(self.name, "down", retryable=True)
        return FinderResult(email=self.answer, provider=self.name)


class FakeVerifier:
    name = "verifier"

    def __init__(self, answers: dict[str, VerificationStatus]) -> None:
        self.answers = answers
        self.checked: list[str] = []

    def verify(self, email: str) -> VerificationResult:
        self.checked.append(email)
        return VerificationResult(
            email=email, status=self.answers.get(email, V.INVALID), provider=self.name
        )


class FakeResolver:
    name = "resolver"

    def __init__(self, result: ResolutionStatus | None, *, ref: str = "job-1") -> None:
        self.result = result
        self.ref = ref
        self.submitted: list[str] = []

    def submit(self, email: str) -> ResolutionTicket:
        self.submitted.append(email)
        done = (
            ResolutionResult(email=email, status=self.result, provider=self.name)
            if self.result
            else None
        )
        return ResolutionTicket(ref=self.ref, email=email, provider=self.name, result=done)

    def poll(self, ticket: ResolutionTicket) -> ResolutionResult | None:
        return None


JANE = Contact(
    id="c1",
    workspace_id="w",
    company_id="co",
    rank=1,
    source=ContactSource.SITE,
    status=ContactStatus.CANDIDATE,
    full_name="Jane Doe",
    first_name="Jane",
    last_name="Doe",
)
TARGET = Target(domain="acme.com", name="Acme")


def held(
    email: str,
    status: EmailStatus,
    provenance: Provenance = Provenance.OPERATOR_GIVEN,
    ref: str | None = None,
) -> ContactEmail:
    return ContactEmail(
        id=f"e-{email}",
        workspace_id="w",
        contact_id="c1",
        status=status,
        provenance=provenance,
        is_primary=False,
        email=email,
        resolution_ref=ref,
    )


def run(
    finders: list[FakeFinder],
    verifier: FakeVerifier,
    *,
    resolver: FakeResolver | None = None,
    emails: list[ContactEmail] | None = None,
    target: Target = TARGET,
    contact: Contact = JANE,
) -> Outcome:
    return Waterfall(finders, verifier, resolver).run(contact, emails or [], target)


# ------------------------------------------------------------------ order and stopping


def test_the_first_finder_that_yields_a_valid_address_stops_the_search() -> None:
    first = FakeFinder("hunter", "jane.doe@acme.com")
    second = FakeFinder("zerobounce", "jdoe@acme.com")
    verifier = FakeVerifier({"jane.doe@acme.com": V.VALID})
    out = run([first, second], verifier)
    assert out.verdict is Verdict.READY
    assert out.chosen is not None
    assert (out.chosen.email, out.chosen.status, out.chosen.provenance) == (
        "jane.doe@acme.com",
        E.VALID,
        Provenance.API_DATABASE,
    )
    assert (out.chosen.found_by, out.chosen.verified_by) == ("hunter", "verifier")
    assert second.calls == 0


def test_an_invalid_first_result_falls_through_to_the_next_finder() -> None:
    first = FakeFinder("hunter", "old@acme.com")
    second = FakeFinder("zerobounce", "jane.doe@acme.com")
    verifier = FakeVerifier({"jane.doe@acme.com": V.VALID})
    out = run([first, second], verifier)
    assert verifier.checked == ["old@acme.com", "jane.doe@acme.com"]
    assert out.chosen is not None and out.chosen.email == "jane.doe@acme.com"
    assert [(r.email, r.status) for r in out.records] == [
        ("old@acme.com", E.INVALID),
        ("jane.doe@acme.com", E.VALID),
    ]


def test_a_finder_that_finds_nothing_costs_no_verification() -> None:
    verifier = FakeVerifier({})
    out = run([FakeFinder("hunter", None), FakeFinder("zerobounce", None)], verifier)
    assert (out.verdict, verifier.checked, out.records) == (Verdict.NONE, [], [])


def test_the_same_address_from_two_finders_is_verified_once() -> None:
    verifier = FakeVerifier({"x@acme.com": V.UNKNOWN})
    out = run([FakeFinder("a", "x@acme.com"), FakeFinder("b", "X@acme.com")], verifier)
    assert verifier.checked == ["x@acme.com"]
    assert out.records[0].status is E.UNKNOWN


def test_a_failing_finder_is_skipped_and_reported() -> None:
    good = FakeFinder("zerobounce", "jane.doe@acme.com")
    out = run([FakeFinder("hunter", fail=True), good], FakeVerifier({"jane.doe@acme.com": V.VALID}))
    assert out.verdict is Verdict.READY
    assert any("hunter" in problem for problem in out.problems)


def test_a_failing_verifier_leaves_the_address_unproven() -> None:
    class Broken:
        name = "verifier"

        def verify(self, email: str) -> VerificationResult:
            raise ProviderError("verifier", "down")

    out = Waterfall([FakeFinder("hunter", "jane.doe@acme.com")], Broken()).run(JANE, [], TARGET)
    assert out.verdict is Verdict.NONE and out.records == []
    assert any("verifier" in p for p in out.problems)


def test_a_person_with_no_surname_cannot_be_searched_for() -> None:
    nameless = Contact(
        id="c2",
        workspace_id="w",
        company_id="co",
        rank=1,
        source=ContactSource.SITE,
        status=ContactStatus.CANDIDATE,
        full_name="Cher",
        first_name="Cher",
    )
    finder = FakeFinder("hunter", "cher@acme.com")
    out = run([finder], FakeVerifier({}), contact=nameless)
    assert finder.calls == 0
    assert any("first and last name" in p for p in out.problems)


# ------------------------------------------------------------------ cheaper sources first


def test_a_learned_pattern_builds_exactly_one_address_and_skips_the_finders() -> None:
    finder = FakeFinder("hunter", "other@acme.com")
    verifier = FakeVerifier({"jane.doe@acme.com": V.VALID})
    out = run([finder], verifier, target=Target("acme.com", "Acme", pattern="{first}.{last}"))
    assert verifier.checked == ["jane.doe@acme.com"]
    assert finder.calls == 0
    assert out.chosen is not None
    assert (out.chosen.provenance, out.chosen.found_by) == (Provenance.PATTERN_INFERRED, None)


def test_a_pattern_address_that_fails_verification_falls_back_to_the_finders() -> None:
    finder = FakeFinder("hunter", "jdoe@acme.com")
    verifier = FakeVerifier({"jdoe@acme.com": V.VALID})
    out = run([finder], verifier, target=Target("acme.com", "Acme", pattern="{first}.{last}"))
    assert verifier.checked == ["jane.doe@acme.com", "jdoe@acme.com"]
    assert out.chosen is not None and out.chosen.email == "jdoe@acme.com"


def test_an_address_published_on_the_site_is_tried_before_anything_paid() -> None:
    finder = FakeFinder("hunter", "other@acme.com")
    verifier = FakeVerifier({"j.doe@acme.com": V.VALID})
    target = Target("acme.com", "Acme", site_emails=("sales@acme.com", "j.doe@acme.com"))
    out = run([finder], verifier, target=target)
    assert finder.calls == 0
    assert out.chosen is not None
    assert out.chosen.provenance is Provenance.PUBLICLY_PUBLISHED


def test_a_finder_result_that_is_on_the_site_is_recorded_as_published() -> None:
    target = Target("acme.com", "Acme", site_emails=("zz@acme.com",))
    out = run(
        [FakeFinder("hunter", "ZZ@acme.com")], FakeVerifier({"zz@acme.com": V.VALID}), target=target
    )
    assert out.chosen is not None
    assert out.chosen.provenance is Provenance.PUBLICLY_PUBLISHED
    assert out.chosen.found_by == "hunter"


# ------------------------------------------------------------------ addresses we already hold


def test_an_operator_address_is_verified_and_the_finders_are_never_called() -> None:
    finder = FakeFinder("hunter", "other@acme.com")
    verifier = FakeVerifier({"jane@acme.com": V.VALID})
    out = run([finder], verifier, emails=[held("jane@acme.com", E.UNVERIFIED)])
    assert out.chosen is not None
    assert (out.chosen.email, out.chosen.existing_id) == ("jane@acme.com", "e-jane@acme.com")
    assert out.chosen.provenance is Provenance.OPERATOR_GIVEN
    assert finder.calls == 0


def test_a_bad_operator_address_is_not_replaced_by_a_finder_guess() -> None:
    finder = FakeFinder("hunter", "other@acme.com")
    verifier = FakeVerifier({"jane@acme.com": V.INVALID})
    out = run([finder], verifier, emails=[held("jane@acme.com", E.UNVERIFIED)])
    assert out.verdict is Verdict.NONE
    assert finder.calls == 0
    assert out.records[0].status is E.INVALID


def test_an_address_already_proven_is_used_without_any_call() -> None:
    verifier = FakeVerifier({})
    out = run(
        [FakeFinder("hunter", "x@acme.com")],
        verifier,
        emails=[held("jane@acme.com", E.VALID, Provenance.API_DATABASE)],
    )
    assert out.chosen is not None and out.chosen.email == "jane@acme.com"
    assert verifier.checked == []


def test_an_address_known_to_be_invalid_is_never_retried_but_the_search_goes_on() -> None:
    finder = FakeFinder("hunter", "jane.doe@acme.com")
    verifier = FakeVerifier({"jane.doe@acme.com": V.VALID})
    out = run([finder], verifier, emails=[held("old@acme.com", E.INVALID, Provenance.API_DATABASE)])
    assert "old@acme.com" not in verifier.checked
    assert out.chosen is not None and out.chosen.email == "jane.doe@acme.com"


def test_an_address_the_finder_returns_again_after_being_invalid_is_not_rechecked() -> None:
    finder = FakeFinder("hunter", "old@acme.com")
    verifier = FakeVerifier({})
    out = run([finder], verifier, emails=[held("old@acme.com", E.INVALID, Provenance.API_DATABASE)])
    assert verifier.checked == [] and out.verdict is Verdict.NONE


def test_an_unresolved_catch_all_is_usable_only_when_the_safeguard_is_off() -> None:
    mail = held("jane@acme.com", E.CATCH_ALL_UNVERIFIED, Provenance.API_DATABASE)
    safe = run([], FakeVerifier({}), emails=[mail])
    assert safe.verdict is Verdict.NONE and safe.catch_all_unverified
    relaxed = run(
        [],
        FakeVerifier({}),
        emails=[mail],
        target=Target("acme.com", "Acme", safe_to_send_only=False),
    )
    assert relaxed.verdict is Verdict.READY


def test_a_pending_address_keeps_the_company_waiting() -> None:
    out = run(
        [FakeFinder("hunter", "x@acme.com")],
        FakeVerifier({}),
        emails=[held("jane@acme.com", E.CATCH_ALL_PENDING, Provenance.API_DATABASE, "job-9")],
    )
    assert out.verdict is Verdict.PENDING


# ------------------------------------------------------------------ catch-all


def test_a_catch_all_goes_to_the_resolver_and_a_real_time_answer_decides() -> None:
    resolver = FakeResolver(ResolutionStatus.VALID)
    out = run(
        [FakeFinder("hunter", "jane.doe@acme.com")],
        FakeVerifier({"jane.doe@acme.com": V.CATCH_ALL}),
        resolver=resolver,
    )
    assert out.verdict is Verdict.READY
    assert out.chosen is not None and out.chosen.status is E.CATCH_ALL_RESOLVED
    assert resolver.submitted == ["jane.doe@acme.com"]


def test_a_resolver_that_says_invalid_moves_on_to_the_next_finder() -> None:
    resolver = FakeResolver(ResolutionStatus.INVALID)
    second = FakeFinder("zerobounce", "jdoe@acme.com")
    verifier = FakeVerifier({"a@acme.com": V.CATCH_ALL, "jdoe@acme.com": V.VALID})
    out = run([FakeFinder("hunter", "a@acme.com"), second], verifier, resolver=resolver)
    assert out.chosen is not None and out.chosen.email == "jdoe@acme.com"


def test_an_asynchronous_resolver_leaves_a_pending_address_and_stops_the_search() -> None:
    resolver = FakeResolver(None, ref="job-77")
    second = FakeFinder("zerobounce", "jdoe@acme.com")
    out = run(
        [FakeFinder("hunter", "a@acme.com"), second],
        FakeVerifier({"a@acme.com": V.CATCH_ALL}),
        resolver=resolver,
    )
    assert out.verdict is Verdict.PENDING
    assert second.calls == 0
    assert [(r.status, r.resolution_ref) for r in out.records] == [(E.CATCH_ALL_PENDING, "job-77")]


def test_an_undecided_resolver_leaves_the_address_unverified() -> None:
    out = run(
        [FakeFinder("hunter", "a@acme.com")],
        FakeVerifier({"a@acme.com": V.CATCH_ALL}),
        resolver=FakeResolver(ResolutionStatus.UNRESOLVED),
    )
    assert out.verdict is Verdict.NONE and out.catch_all_unverified
    assert out.records[0].status is E.CATCH_ALL_UNVERIFIED


def test_without_a_resolver_a_catch_all_is_unverified() -> None:
    out = run([FakeFinder("hunter", "a@acme.com")], FakeVerifier({"a@acme.com": V.CATCH_ALL}))
    assert out.catch_all_unverified
    assert out.records[0].status is E.CATCH_ALL_UNVERIFIED
