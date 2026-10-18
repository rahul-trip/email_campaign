"""Bake-off logic with fake adapters: no network, no spend."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from outbound.providers.errors import ProviderAuthError, ProviderError
from outbound.providers.ports import (
    FinderResult,
    PersonQuery,
    ResolutionResult,
    ResolutionStatus,
    ResolutionTicket,
    VerificationResult,
    VerificationStatus,
)
from scripts import bakeoff
from scripts.bakeoff import (
    ChainResult,
    Contact,
    Matrix,
    collect,
    evaluate_chain,
    load_contacts,
    poll_pending,
    verifier_quality,
)

PRICES: dict[str, int | None] = {
    "f1:find": 100,
    "f2:find": 300,
    "v:verify": 10,
    "r:resolve": 1_000,
    "async:resolve": None,
}

JANE = Contact("Jane Doe", "Jane", "Doe", "acme.com", "US", "jane@acme.com")
SAM = Contact("Sam Roe", "Sam", "Roe", "beta.io", "GB", "sam@beta.io")


# ------------------------------------------------------------------ fakes


class FakeFinder:
    def __init__(self, name: str, answers: dict[str, str | None], *, billed: bool = True) -> None:
        self.name = name
        self._answers = answers  # last_name -> email
        self._billed = billed
        self.calls = 0

    def find(self, person: PersonQuery, domain: str) -> FinderResult:
        self.calls += 1
        email = self._answers.get(person.last_name)
        return FinderResult(
            email=email, provider=self.name, billed=email is not None and self._billed
        )


class FakeVerifier:
    name = "v"

    def __init__(self, statuses: dict[str, VerificationStatus]) -> None:
        self._statuses = statuses
        self.calls = 0

    def verify(self, email: str) -> VerificationResult:
        self.calls += 1
        return VerificationResult(
            email=email,
            status=self._statuses.get(email, VerificationStatus.UNKNOWN),
            provider=self.name,
        )


class FakeResolver:
    def __init__(self, name: str, outcomes: dict[str, ResolutionStatus], *, realtime: bool) -> None:
        self.name = name
        self._outcomes = outcomes
        self._realtime = realtime
        self.ready = False
        self.submits = 0

    def submit(self, email: str) -> ResolutionTicket:
        self.submits += 1
        result = None
        if self._realtime:
            result = ResolutionResult(email=email, status=self._outcomes[email], provider=self.name)
        return ResolutionTicket(ref=f"t-{email}", email=email, provider=self.name, result=result)

    def poll(self, ticket: ResolutionTicket) -> ResolutionResult | None:
        if not self.ready:
            return None
        return ResolutionResult(
            email=ticket.email, status=self._outcomes[ticket.email], provider=self.name
        )


def collected(
    contacts: list[Contact],
    finders: dict[str, FakeFinder],
    verifier: FakeVerifier,
    resolvers: dict[str, FakeResolver] | None = None,
) -> Matrix:
    matrix = Matrix()
    collect(contacts, finders, {"v": verifier}, resolvers or {}, matrix, log=lambda _: None)
    return matrix


def need[T](value: T | None) -> T:
    assert value is not None
    return value


V = VerificationStatus
R = ResolutionStatus


def chain(
    matrix: Matrix, contacts: list[Contact], finders: tuple[str, ...], resolver: str | None = None
) -> ChainResult:
    return evaluate_chain(
        contacts, matrix, finders=finders, verifier="v", resolver=resolver, prices=PRICES
    )


# ------------------------------------------------------------------ loading contacts


def write_contacts(
    tmp_path: Path, rows: list[str], header: str = "first_name,last_name,domain,country,known_email"
) -> Path:
    path = tmp_path / "contacts.csv"
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


def test_load_contacts_normalises_case_and_builds_full_name(tmp_path: Path) -> None:
    path = write_contacts(tmp_path, ["Jane,Doe,ACME.com,us,Jane@Acme.com"])
    (contact,) = load_contacts(path)
    assert contact == Contact("Jane Doe", "Jane", "Doe", "acme.com", "US", "jane@acme.com")


def test_load_contacts_rejects_a_missing_column(tmp_path: Path) -> None:
    path = write_contacts(tmp_path, ["Jane,Doe,acme.com"], header="first_name,last_name,domain")
    with pytest.raises(ValueError, match="known_email"):
        load_contacts(path)


def test_load_contacts_rejects_a_blank_required_value(tmp_path: Path) -> None:
    path = write_contacts(tmp_path, ["Jane,,acme.com,US,jane@acme.com"])
    with pytest.raises(ValueError, match="line 2"):
        load_contacts(path)


# ------------------------------------------------------------------ collecting


def test_collect_asks_every_finder_and_verifies_found_and_known_addresses() -> None:
    f1 = FakeFinder("f1", {"Doe": "jane@acme.com", "Roe": "wrong@beta.io"})
    verifier = FakeVerifier(
        {"jane@acme.com": V.VALID, "wrong@beta.io": V.INVALID, "sam@beta.io": V.VALID}
    )
    matrix = collected([JANE, SAM], {"f1": f1}, verifier)
    assert f1.calls == 2
    assert {r.email for r in matrix.verifies} == {"jane@acme.com", "wrong@beta.io", "sam@beta.io"}


def test_collect_is_idempotent_so_a_rerun_spends_nothing() -> None:
    f1 = FakeFinder("f1", {"Doe": "jane@acme.com"})
    verifier = FakeVerifier({"jane@acme.com": V.VALID})
    matrix = collected([JANE], {"f1": f1}, verifier)
    first = (f1.calls, verifier.calls)
    collect([JANE], {"f1": f1}, {"v": verifier}, {}, matrix, log=lambda _: None)
    assert (f1.calls, verifier.calls) == first


def test_bad_credentials_abort_the_run_after_saving_progress() -> None:
    class Broken:
        name = "broken"

        def find(self, person: PersonQuery, domain: str) -> FinderResult:
            raise ProviderAuthError("broken", "401")

    saved: list[int] = []
    with pytest.raises(ProviderAuthError):
        collect(
            [JANE],
            {"broken": Broken()},
            {},
            {},
            Matrix(),
            save=lambda: saved.append(1),
            log=lambda _: None,
        )


def test_other_provider_errors_are_recorded_and_the_run_continues() -> None:
    class Flaky:
        name = "flaky"

        def find(self, person: PersonQuery, domain: str) -> FinderResult:
            if person.last_name == "Doe":
                raise ProviderError("flaky", "boom")
            return FinderResult(email="sam@beta.io", provider="flaky")

    matrix = Matrix()
    collect([JANE, SAM], {"flaky": Flaky()}, {}, {}, matrix, log=lambda _: None)
    assert (
        need(matrix.find_of(0, "flaky")).error
        and need(matrix.find_of(1, "flaky")).email == "sam@beta.io"
    )


def test_catch_all_addresses_are_sent_to_resolvers_once() -> None:
    f1 = FakeFinder("f1", {"Doe": "jane@acme.com"})
    verifier = FakeVerifier({"jane@acme.com": V.CATCH_ALL, "sam@beta.io": V.VALID})
    realtime = FakeResolver("r", {"jane@acme.com": R.VALID}, realtime=True)
    matrix = collected([JANE, SAM], {"f1": f1}, verifier, {"r": realtime})
    assert realtime.submits == 1  # jane@acme.com appears twice (found and known) but is asked once
    assert need(matrix.resolve_of("r", "jane@acme.com")).status == "valid"


def test_async_resolutions_stay_pending_until_polled() -> None:
    f1 = FakeFinder("f1", {"Doe": "jane@acme.com"})
    verifier = FakeVerifier({"jane@acme.com": V.CATCH_ALL})
    slow = FakeResolver("async", {"jane@acme.com": R.VALID}, realtime=False)
    started = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
    matrix = Matrix()
    collect(
        [JANE],
        {"f1": f1},
        {"v": verifier},
        {"async": slow},
        matrix,
        now=lambda: started,
        log=lambda _: None,
    )
    assert need(matrix.resolve_of("async", "jane@acme.com")).status is None

    assert poll_pending(matrix, {"async": slow}, now=lambda: started + timedelta(hours=30)) == 0
    slow.ready = True
    assert poll_pending(matrix, {"async": slow}, now=lambda: started + timedelta(hours=30)) == 1
    record = matrix.resolve_of("async", "jane@acme.com")
    assert record is not None and record.status == "valid"
    assert record.elapsed_seconds == 30 * 3600
    assert poll_pending(matrix, {"async": slow}, now=lambda: started) == 0  # nothing left


def test_matrix_survives_a_save_and_load(tmp_path: Path) -> None:
    f1 = FakeFinder("f1", {"Doe": "jane@acme.com"})
    matrix = collected([JANE], {"f1": f1}, FakeVerifier({"jane@acme.com": V.VALID}))
    matrix.save(tmp_path / "m.json")
    assert Matrix.load(tmp_path / "m.json") == matrix
    assert Matrix.load(tmp_path / "missing.json") == Matrix()


# ------------------------------------------------------------------ evaluating chains


def test_a_valid_first_finder_stops_the_chain_and_only_billed_calls_cost() -> None:
    f1 = FakeFinder("f1", {"Doe": "jane@acme.com"})
    f2 = FakeFinder("f2", {"Doe": "jane@acme.com"})
    matrix = collected([JANE], {"f1": f1, "f2": f2}, FakeVerifier({"jane@acme.com": V.VALID}))
    result = chain(matrix, [JANE], ("f1", "f2"))
    assert (result.safe, result.right_and_safe, result.wrong_but_safe) == (1, 1, 0)
    assert result.cost_micro_usd == 100 + 10  # f2 was never reached, so it costs nothing
    assert result.cost_per_safe_usd == pytest.approx(0.00011)


def test_an_invalid_address_moves_on_to_the_next_finder() -> None:
    f1 = FakeFinder("f1", {"Doe": "old@acme.com"})
    f2 = FakeFinder("f2", {"Doe": "jane@acme.com"})
    verifier = FakeVerifier({"old@acme.com": V.INVALID, "jane@acme.com": V.VALID})
    matrix = collected([JANE], {"f1": f1, "f2": f2}, verifier)
    result = chain(matrix, [JANE], ("f1", "f2"))
    assert result.right_and_safe == 1
    assert result.found_correct == 1
    assert result.cost_micro_usd == 100 + 10 + 300 + 10


def test_a_safe_but_unknown_address_is_counted_as_wrong_but_safe() -> None:
    f1 = FakeFinder("f1", {"Doe": "someone.else@acme.com"})
    matrix = collected(
        [JANE],
        {"f1": f1},
        FakeVerifier({"someone.else@acme.com": V.VALID, "jane@acme.com": V.VALID}),
    )
    result = chain(matrix, [JANE], ("f1",))
    assert (result.safe, result.right_and_safe, result.wrong_but_safe) == (1, 0, 1)
    assert result.found_correct == 0


def test_a_catch_all_is_safe_only_if_the_resolver_settles_it() -> None:
    f1 = FakeFinder("f1", {"Doe": "jane@acme.com", "Roe": "sam@beta.io"})
    verifier = FakeVerifier({"jane@acme.com": V.CATCH_ALL, "sam@beta.io": V.CATCH_ALL})
    resolver = FakeResolver(
        "r", {"jane@acme.com": R.VALID, "sam@beta.io": R.UNRESOLVED}, realtime=True
    )
    matrix = collected([JANE, SAM], {"f1": f1}, verifier, {"r": resolver})

    with_resolver = chain(matrix, [JANE, SAM], ("f1",), "r")
    assert (with_resolver.safe, with_resolver.held) == (1, 1)
    assert with_resolver.cost_micro_usd == 2 * (100 + 10 + 1_000)

    without = chain(matrix, [JANE, SAM], ("f1",), None)
    assert (without.safe, without.held) == (0, 0)  # a raw catch-all is never sent to


def test_a_held_catch_all_stops_the_chain_so_the_next_finder_is_not_paid() -> None:
    f1 = FakeFinder("f1", {"Doe": "jane@acme.com"})
    f2 = FakeFinder("f2", {"Doe": "jane@acme.com"})
    verifier = FakeVerifier({"jane@acme.com": V.CATCH_ALL})
    resolver = FakeResolver("r", {"jane@acme.com": R.UNRESOLVED}, realtime=True)
    matrix = collected([JANE], {"f1": f1, "f2": f2}, verifier, {"r": resolver})
    result = chain(matrix, [JANE], ("f1", "f2"), "r")
    assert result.held == 1
    assert result.cost_micro_usd == 100 + 10 + 1_000


def test_calls_the_vendor_did_not_bill_are_free_and_unpriced_ones_are_counted() -> None:
    f1 = FakeFinder("f1", {"Doe": "jane@acme.com"}, billed=False)
    verifier = FakeVerifier({"jane@acme.com": V.CATCH_ALL})
    slow = FakeResolver("async", {"jane@acme.com": R.VALID}, realtime=True)
    matrix = collected([JANE], {"f1": f1}, verifier, {"async": slow})
    result = chain(matrix, [JANE], ("f1",), "async")
    assert result.cost_micro_usd == 10  # only the verifier was billed and priced
    assert result.unpriced_calls == 1  # the resolver call is billed but has no known price


def test_no_safe_address_means_no_cost_per_safe_figure() -> None:
    f1 = FakeFinder("f1", {"Doe": None})
    matrix = collected([JANE], {"f1": f1}, FakeVerifier({}))
    assert chain(matrix, [JANE], ("f1",)).cost_per_safe_usd is None


def test_median_resolve_time_comes_from_resolved_records() -> None:
    matrix = Matrix()
    contacts = [JANE]
    f1 = FakeFinder("f1", {"Doe": "jane@acme.com"})
    collect(
        contacts,
        {"f1": f1},
        {"v": FakeVerifier({"jane@acme.com": V.CATCH_ALL})},
        {},
        matrix,
        log=lambda _: None,
    )
    matrix.resolves.append(
        bakeoff.ResolveRecord(
            "r", "jane@acme.com", "t", "2026-10-16T00:00:00+00:00", "valid", True, 7200.0
        )
    )
    assert chain(matrix, contacts, ("f1",), "r").median_resolve_seconds == 7200.0


def test_all_chains_covers_every_finder_order_verifier_and_resolver_choice() -> None:
    f1 = FakeFinder("f1", {"Doe": "jane@acme.com"})
    f2 = FakeFinder("f2", {"Doe": "jane@acme.com"})
    resolver = FakeResolver("r", {"jane@acme.com": R.VALID}, realtime=True)
    matrix = collected(
        [JANE], {"f1": f1, "f2": f2}, FakeVerifier({"jane@acme.com": V.CATCH_ALL}), {"r": resolver}
    )
    results = bakeoff.all_chains([JANE], matrix, PRICES)
    # finder orders: f1, f2, f1>f2, f2>f1 = 4; resolvers: none or r = 2; one verifier
    assert len(results) == 8
    assert len({r.label for r in results}) == 8


def test_verifier_quality_flags_false_rejects_of_known_good_addresses() -> None:
    verifier = FakeVerifier({"jane@acme.com": V.VALID, "sam@beta.io": V.INVALID})
    matrix = collected([JANE, SAM], {}, verifier)
    (row,) = verifier_quality([JANE, SAM], matrix)
    assert (row.checked, row.valid, row.invalid) == (2, 1, 1)


# ------------------------------------------------------------------ reporting and recording


def test_report_and_summary_name_each_chain(tmp_path: Path) -> None:
    f1 = FakeFinder("f1", {"Doe": "jane@acme.com"})
    matrix = collected([JANE], {"f1": f1}, FakeVerifier({"jane@acme.com": V.VALID}))
    results = bakeoff.all_chains([JANE], matrix, PRICES)
    path = tmp_path / "report.csv"
    bakeoff.write_report(results, path)
    rows = list(csv.DictReader(path.open()))
    assert rows[0]["chain"] == "f1 | v | no resolver"
    assert rows[0]["right_and_safe"] == "1"
    text = bakeoff.summary(results, verifier_quality([JANE], matrix))
    assert "f1 | v | no resolver" in text and "$0.000" in text


def test_recording_client_saves_bodies_but_never_the_query_string(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"status": "valid"}))
    client = bakeoff.recording_client(tmp_path, transport=transport)
    client.get("https://api.example.test/v1/verify?email=a@b.com&api_key=SECRET")
    (saved,) = tmp_path.glob("*.json")
    text = saved.read_text()
    assert json.loads(text) == {
        "method": "GET",
        "path": "/v1/verify",
        "status": 200,
        "body": {"status": "valid"},
    }
    assert "SECRET" not in text


def test_the_report_command_runs_from_saved_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    f1 = FakeFinder("f1", {"Doe": "jane@acme.com"})
    matrix = collected([JANE], {"f1": f1}, FakeVerifier({"jane@acme.com": V.VALID}))
    matrix.save(tmp_path / "bakeoff_matrix.json")
    write_contacts(tmp_path, ["Jane,Doe,acme.com,US,jane@acme.com"]).rename(
        tmp_path / "bakeoff_contacts.csv"
    )
    assert bakeoff.main(["--dir", str(tmp_path), "report"]) == 0
    assert "f1 | v | no resolver" in capsys.readouterr().out
    assert (tmp_path / "bakeoff_report.csv").exists()


def test_collect_refuses_to_run_with_no_keys_configured(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("HUNTER", "ZEROBOUNCE", "ORBISEARCH", "MYEMAILVERIFIER"):
        monkeypatch.delenv(f"{name}_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)  # so no .env is found
    contacts = write_contacts(tmp_path, ["Jane,Doe,acme.com,US,jane@acme.com"])
    assert bakeoff.main(["--dir", str(tmp_path), "collect", "--contacts", str(contacts)]) == 2
    assert "nothing to run" in capsys.readouterr().err
