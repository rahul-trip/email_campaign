"""Phase 0 vendor bake-off: pick the email waterfall from data, not from vendor claims.

Workflow (all files live in the git-ignored ``data/private/``):

1. ``collect``: run every configured finder over the contacts, verify every address found
   (and every known address), and send catch-all addresses to every configured resolver.
   Every raw answer is saved to ``bakeoff_matrix.json``; anything already saved is never
   asked, or paid for, again.
2. ``poll``: collect the answers of asynchronous resolvers (Scrubby takes 24 to 72 hours).
3. ``report``: simulate every chain order from the saved answers, offline and for free, and
   write ``bakeoff_report.csv`` plus a printed summary.

Run from the repo root, for example::

    uv run python -m scripts.bakeoff collect --contacts data/private/bakeoff_contacts.csv
    uv run python -m scripts.bakeoff poll
    uv run python -m scripts.bakeoff report
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import statistics
import sys
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

import httpx

from outbound.config import Settings
from outbound.providers.errors import BudgetExceeded, ProviderAuthError, ProviderError
from outbound.providers.ports import (
    CatchAllResolver,
    EmailFinder,
    EmailVerifier,
    PersonQuery,
    ResolutionStatus,
    ResolutionTicket,
    VerificationStatus,
)
from outbound.providers.pricing import DEFAULT_PRICES
from outbound.providers.registry import (
    configured_finders,
    configured_resolvers,
    configured_verifiers,
)

DATA_DIR = Path("data/private")


# --------------------------------------------------------------------------- input


@dataclass(frozen=True)
class Contact:
    full_name: str
    first_name: str
    last_name: str
    domain: str
    country: str
    known_email: str


_REQUIRED = ("first_name", "last_name", "domain", "known_email")


def load_contacts(path: Path) -> list[Contact]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = [name for name in _REQUIRED if name not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path} is missing column(s): {missing}")
        contacts = []
        for line, row in enumerate(reader, start=2):
            values = {key: (row.get(key) or "").strip() for key in reader.fieldnames or []}
            blanks = [name for name in _REQUIRED if not values[name]]
            if blanks:
                raise ValueError(f"{path} line {line}: blank {blanks}")
            contacts.append(
                Contact(
                    full_name=values.get("full_name")
                    or f"{values['first_name']} {values['last_name']}",
                    first_name=values["first_name"],
                    last_name=values["last_name"],
                    domain=values["domain"].lower(),
                    country=values.get("country", "").upper(),
                    known_email=values["known_email"].lower(),
                )
            )
    return contacts


# --------------------------------------------------------------------------- recorded answers


@dataclass(frozen=True)
class FindRecord:
    contact: int
    finder: str
    email: str | None
    billed: bool
    seconds: float
    error: str | None = None


@dataclass(frozen=True)
class VerifyRecord:
    verifier: str
    email: str
    status: str  # VerificationStatus value; "error" when the call failed
    billed: bool
    seconds: float
    error: str | None = None


@dataclass
class ResolveRecord:
    resolver: str
    email: str
    ticket_ref: str
    submitted_at: str
    status: str | None  # ResolutionStatus value; None while an async resolver is still working
    billed: bool = True
    elapsed_seconds: float | None = None
    error: str | None = None


@dataclass
class Matrix:
    finds: list[FindRecord] = field(default_factory=list)
    verifies: list[VerifyRecord] = field(default_factory=list)
    resolves: list[ResolveRecord] = field(default_factory=list)

    def find_of(self, contact: int, finder: str) -> FindRecord | None:
        return next((r for r in self.finds if r.contact == contact and r.finder == finder), None)

    def verify_of(self, verifier: str, email: str) -> VerifyRecord | None:
        return next((r for r in self.verifies if r.verifier == verifier and r.email == email), None)

    def resolve_of(self, resolver: str, email: str) -> ResolveRecord | None:
        return next((r for r in self.resolves if r.resolver == resolver and r.email == email), None)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2) + "\n")

    @classmethod
    def load(cls, path: Path) -> Matrix:
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text())
        return cls(
            finds=[FindRecord(**r) for r in raw.get("finds", [])],
            verifies=[VerifyRecord(**r) for r in raw.get("verifies", [])],
            resolves=[ResolveRecord(**r) for r in raw.get("resolves", [])],
        )


# --------------------------------------------------------------------------- collecting


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _no_save() -> None:
    return None


def _attempt[T](call: Callable[[], T]) -> tuple[T | None, str | None, float]:
    """Run one vendor call. Bad credentials and spend caps abort the whole run; anything else
    is recorded as that cell's error so one failure does not waste the rest."""
    started = time.monotonic()
    try:
        return call(), None, time.monotonic() - started
    except (ProviderAuthError, BudgetExceeded):
        raise
    except ProviderError as exc:
        return None, str(exc), time.monotonic() - started


def collect(
    contacts: list[Contact],
    finders: Mapping[str, EmailFinder],
    verifiers: Mapping[str, EmailVerifier],
    resolvers: Mapping[str, CatchAllResolver],
    matrix: Matrix,
    *,
    save: Callable[[], None] = _no_save,
    now: Callable[[], datetime] = _utcnow,
    log: Callable[[str], None] = print,
) -> None:
    """Fill the matrix. Idempotent: a cell that is already recorded is never asked again."""
    _collect_finds(contacts, finders, matrix, save)
    log(f"finders done: {len(matrix.finds)} answers")
    _collect_verifications(contacts, verifiers, matrix, save)
    log(f"verifiers done: {len(matrix.verifies)} answers")
    _collect_resolutions(resolvers, matrix, save, now)
    log(f"resolvers done: {len(matrix.resolves)} submissions")


def _collect_finds(
    contacts: list[Contact],
    finders: Mapping[str, EmailFinder],
    matrix: Matrix,
    save: Callable[[], None],
) -> None:
    for index, contact in enumerate(contacts):
        person = PersonQuery(first_name=contact.first_name, last_name=contact.last_name)
        for name, finder in finders.items():
            if matrix.find_of(index, name) is not None:
                continue
            found, error, seconds = _attempt(partial(finder.find, person, contact.domain))
            matrix.finds.append(
                FindRecord(
                    contact=index,
                    finder=name,
                    email=found.email if found else None,
                    billed=found.billed if found else False,
                    seconds=round(seconds, 3),
                    error=error,
                )
            )
        save()


def _collect_verifications(
    contacts: list[Contact],
    verifiers: Mapping[str, EmailVerifier],
    matrix: Matrix,
    save: Callable[[], None],
) -> None:
    for email in _emails_to_verify(contacts, matrix):
        for name, verifier in verifiers.items():
            if matrix.verify_of(name, email) is not None:
                continue
            verdict, error, seconds = _attempt(partial(verifier.verify, email))
            matrix.verifies.append(
                VerifyRecord(
                    verifier=name,
                    email=email,
                    status=verdict.status.value if verdict else "error",
                    billed=verdict.billed if verdict else False,
                    seconds=round(seconds, 3),
                    error=error,
                )
            )
        save()


def _collect_resolutions(
    resolvers: Mapping[str, CatchAllResolver],
    matrix: Matrix,
    save: Callable[[], None],
    now: Callable[[], datetime],
) -> None:
    for email in _catch_all_emails(matrix):
        for name, resolver in resolvers.items():
            if matrix.resolve_of(name, email) is not None:
                continue
            submitted_at = now().isoformat()
            ticket, error, seconds = _attempt(partial(resolver.submit, email))
            if ticket is None:
                record = ResolveRecord(name, email, "", submitted_at, None, False, None, error)
            elif ticket.result is not None:  # a real-time resolver answered at once
                record = ResolveRecord(
                    name,
                    email,
                    ticket.ref,
                    submitted_at,
                    ticket.result.status.value,
                    ticket.result.billed,
                    round(seconds, 3),
                )
            else:  # asynchronous: collect the answer later with `poll`
                record = ResolveRecord(name, email, ticket.ref, submitted_at, None)
            matrix.resolves.append(record)
        save()


def _emails_to_verify(contacts: list[Contact], matrix: Matrix) -> list[str]:
    found = [r.email for r in matrix.finds if r.email]
    known = [c.known_email for c in contacts]
    return list(dict.fromkeys([*found, *known]))  # unique, in a stable order


def _catch_all_emails(matrix: Matrix) -> list[str]:
    flagged = VerificationStatus.CATCH_ALL.value
    return list(dict.fromkeys(r.email for r in matrix.verifies if r.status == flagged))


def poll_pending(
    matrix: Matrix,
    resolvers: Mapping[str, CatchAllResolver],
    *,
    now: Callable[[], datetime] = _utcnow,
) -> int:
    """Ask async resolvers about everything still pending. Returns how many just finished."""
    finished = 0
    for record in matrix.resolves:
        resolver = resolvers.get(record.resolver)
        if record.status is not None or record.error or resolver is None:
            continue
        ticket = ResolutionTicket(
            ref=record.ticket_ref, email=record.email, provider=record.resolver
        )
        result, error, _ = _attempt(partial(resolver.poll, ticket))
        if error:
            record.error = error
        elif result is not None:
            record.status = result.status.value
            record.billed = result.billed
            started = datetime.fromisoformat(record.submitted_at)
            record.elapsed_seconds = round((now() - started).total_seconds(), 1)
            finished += 1
    return finished


# --------------------------------------------------------------------------- evaluating chains


@dataclass(frozen=True)
class ChainResult:
    finders: tuple[str, ...]
    verifier: str
    resolver: str | None
    contacts: int
    found: int  # some finder returned an address
    found_correct: int  # some finder returned the known address
    safe: int  # ended with an address that is safe to send
    right_and_safe: int  # ... and it is the known address
    wrong_but_safe: int  # safe, but not the known address: the dangerous case
    held: int  # ended on a catch-all the resolver could not settle
    cost_micro_usd: int
    unpriced_calls: int
    median_resolve_seconds: float | None

    @property
    def cost_per_safe_usd(self) -> float | None:
        return self.cost_micro_usd / self.safe / 1_000_000 if self.safe else None

    @property
    def label(self) -> str:
        return " > ".join(self.finders) + f" | {self.verifier} | {self.resolver or 'no resolver'}"


class _Ledger:
    def __init__(self, prices: dict[str, int | None]) -> None:
        self._prices = prices
        self.micro_usd = 0
        self.unpriced = 0

    def charge(self, provider: str, operation: str, billed: bool) -> None:
        if not billed:
            return
        price = self._prices.get(f"{provider}:{operation}")
        if price is None:
            self.unpriced += 1
        else:
            self.micro_usd += price


def evaluate_chain(
    contacts: list[Contact],
    matrix: Matrix,
    *,
    finders: tuple[str, ...],
    verifier: str,
    resolver: str | None,
    prices: dict[str, int | None],
) -> ChainResult:
    """Replay one chain over the saved answers, exactly as the Phase 2 email stage will run."""
    ledger = _Ledger(prices)
    found = found_correct = safe = right_and_safe = wrong_but_safe = held = 0
    resolve_times: list[float] = []

    for index, contact in enumerate(contacts):
        any_found = any_correct = False
        outcome_safe: str | None = None
        outcome_held = False
        for name in finders:
            record = matrix.find_of(index, name)
            if record is None:
                continue
            ledger.charge(name, "find", record.billed)
            if not record.email:
                continue
            any_found = True
            any_correct = any_correct or record.email == contact.known_email
            checked = matrix.verify_of(verifier, record.email)
            if checked is None:
                continue
            ledger.charge(verifier, "verify", checked.billed)
            if checked.status == VerificationStatus.VALID.value:
                outcome_safe = record.email
                break
            if checked.status == VerificationStatus.CATCH_ALL.value and resolver:
                settled = matrix.resolve_of(resolver, record.email)
                if settled is not None:
                    ledger.charge(resolver, "resolve", settled.billed)
                    if settled.elapsed_seconds is not None:
                        resolve_times.append(settled.elapsed_seconds)
                    if settled.status == ResolutionStatus.VALID.value:
                        outcome_safe = record.email
                        break
                outcome_held = True
                break
            # INVALID, UNKNOWN, or a catch-all with no resolver: not safe; try the next finder

        found += any_found
        found_correct += any_correct
        if outcome_safe:
            safe += 1
            if outcome_safe == contact.known_email:
                right_and_safe += 1
            else:
                wrong_but_safe += 1
        elif outcome_held:
            held += 1

    return ChainResult(
        finders=finders,
        verifier=verifier,
        resolver=resolver,
        contacts=len(contacts),
        found=found,
        found_correct=found_correct,
        safe=safe,
        right_and_safe=right_and_safe,
        wrong_but_safe=wrong_but_safe,
        held=held,
        cost_micro_usd=ledger.micro_usd,
        unpriced_calls=ledger.unpriced,
        median_resolve_seconds=statistics.median(resolve_times) if resolve_times else None,
    )


def all_chains(
    contacts: list[Contact], matrix: Matrix, prices: dict[str, int | None]
) -> list[ChainResult]:
    finder_names = sorted({r.finder for r in matrix.finds})
    verifier_names = sorted({r.verifier for r in matrix.verifies})
    resolver_names: list[str | None] = [None, *sorted({r.resolver for r in matrix.resolves})]
    results = []
    for length in range(1, len(finder_names) + 1):
        for order in itertools.permutations(finder_names, length):
            for verifier, resolver in itertools.product(verifier_names, resolver_names):
                results.append(
                    evaluate_chain(
                        contacts,
                        matrix,
                        finders=order,
                        verifier=verifier,
                        resolver=resolver,
                        prices=prices,
                    )
                )
    return results


@dataclass(frozen=True)
class VerifierQuality:
    verifier: str
    checked: int
    valid: int
    catch_all: int
    invalid: int  # a known-good address rejected: a false reject
    unknown: int
    errors: int


def verifier_quality(contacts: list[Contact], matrix: Matrix) -> list[VerifierQuality]:
    """How each verifier treats addresses we know work. Invalid here is a false reject."""
    rows = []
    for verifier in sorted({r.verifier for r in matrix.verifies}):
        statuses = [
            record.status
            for contact in contacts
            if (record := matrix.verify_of(verifier, contact.known_email)) is not None
        ]
        count = statuses.count
        rows.append(
            VerifierQuality(
                verifier=verifier,
                checked=len(statuses),
                valid=count("valid"),
                catch_all=count("catch_all"),
                invalid=count("invalid"),
                unknown=count("unknown"),
                errors=count("error"),
            )
        )
    return rows


# --------------------------------------------------------------------------- reporting


def _pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.0f}%" if whole else "-"


def _usd(value: float | None) -> str:
    return "n/a" if value is None else f"${value:.3f}"


def write_report(results: Iterable[ChainResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "chain", "contacts", "found", "found_correct", "safe", "right_and_safe",
                "wrong_but_safe", "held", "cost_usd", "cost_per_safe_usd",
                "unpriced_calls", "median_resolve_seconds",
            ]
        )  # fmt: skip
        for r in results:
            per_safe = r.cost_per_safe_usd
            writer.writerow(
                [
                    r.label, r.contacts, r.found, r.found_correct, r.safe, r.right_and_safe,
                    r.wrong_but_safe, r.held, f"{r.cost_micro_usd / 1_000_000:.4f}",
                    "" if per_safe is None else f"{per_safe:.4f}", r.unpriced_calls,
                    "" if r.median_resolve_seconds is None else r.median_resolve_seconds,
                ]
            )  # fmt: skip


def summary(results: list[ChainResult], quality: list[VerifierQuality]) -> str:
    lines = ["Verifiers on addresses we know work (invalid = a false reject):"]
    for q in quality:
        lines.append(
            f"  {q.verifier:<16} valid {_pct(q.valid, q.checked):>4}"
            f"  catch-all {_pct(q.catch_all, q.checked):>4}"
            f"  invalid {_pct(q.invalid, q.checked):>4}"
            f"  unknown {_pct(q.unknown, q.checked):>4}"
            f"  errors {q.errors}"
        )
    lines += ["", "Chains, best first (most right-and-safe, then cheapest per safe email):"]
    ranked = sorted(results, key=lambda r: (-r.right_and_safe, r.cost_per_safe_usd or 1e9))
    lines.append(
        f"  {'chain':<52} {'found':>5} {'corr.':>5} {'safe':>5}"
        f" {'wrong':>5} {'held':>4} {'$/safe':>8}"
    )
    for r in ranked[:15]:
        lines.append(
            f"  {r.label:<52} {_pct(r.found, r.contacts):>5} {_pct(r.found_correct, r.contacts):>5}"
            f" {_pct(r.safe, r.contacts):>5} {_pct(r.wrong_but_safe, r.contacts):>5}"
            f" {_pct(r.held, r.contacts):>4} {_usd(r.cost_per_safe_usd):>8}"
            + ("  (some calls unpriced)" if r.unpriced_calls else "")
        )
    lines += [
        "",
        "found = a finder returned an address; corr. = it was the known address; wrong = verified",
        "safe but not the known address (the dangerous case); held = unresolved catch-all.",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- command line


def recording_client(directory: Path, transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """An httpx client that saves every response body, for turning into test fixtures.

    Only the method, path, status and body are saved, never the query string, because some
    vendors put the API key there. Bodies contain real addresses: keep the folder private.
    """
    directory.mkdir(parents=True, exist_ok=True)
    counter = itertools.count(1)

    def record(response: httpx.Response) -> None:
        response.read()
        try:
            body: Any = response.json()
        except ValueError:
            body = response.text
        name = f"{response.request.url.host}-{next(counter):04d}.json"
        payload = {
            "method": response.request.method,
            "path": response.request.url.path,
            "status": response.status_code,
            "body": body,
        }
        (directory / name).write_text(json.dumps(payload, indent=2) + "\n")

    return httpx.Client(timeout=30, transport=transport, event_hooks={"response": [record]})


def _load_prices(path: Path | None) -> dict[str, int | None]:
    if path is None:
        return dict(DEFAULT_PRICES)
    return {**DEFAULT_PRICES, **json.loads(path.read_text())}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--dir", type=Path, default=DATA_DIR, help="working folder (git-ignored)")
    commands = parser.add_subparsers(dest="command", required=True)
    collect_cmd = commands.add_parser("collect", help="ask the vendors (spends credits)")
    collect_cmd.add_argument("--contacts", type=Path, required=True)
    collect_cmd.add_argument("--record", type=Path, help="also save raw responses here")
    commands.add_parser("poll", help="collect answers from asynchronous resolvers")
    report_cmd = commands.add_parser("report", help="evaluate every chain from saved answers")
    report_cmd.add_argument("--contacts", type=Path)
    report_cmd.add_argument("--prices", type=Path, help="JSON price overrides")
    args = parser.parse_args(argv)

    matrix_path = args.dir / "bakeoff_matrix.json"
    matrix = Matrix.load(matrix_path)
    settings = Settings()

    if args.command == "report":
        contacts_path = args.contacts or args.dir / "bakeoff_contacts.csv"
        contacts = load_contacts(contacts_path)
        results = all_chains(contacts, matrix, _load_prices(args.prices))
        write_report(results, args.dir / "bakeoff_report.csv")
        print(summary(results, verifier_quality(contacts, matrix)))
        print(f"\nFull table: {args.dir / 'bakeoff_report.csv'}")
        return 0

    client = recording_client(args.record) if getattr(args, "record", None) else None
    resolvers = configured_resolvers(settings, client)
    try:
        if args.command == "poll":
            done = poll_pending(matrix, resolvers)
            print(f"{done} pending resolution(s) finished")
        else:
            contacts = load_contacts(args.contacts)
            finders = configured_finders(settings, client)
            verifiers = configured_verifiers(settings, client)
            if not finders or not verifiers:
                print(
                    "nothing to run: set at least one finder key (HUNTER_API_KEY or "
                    "ZEROBOUNCE_API_KEY) and one verifier key (HUNTER, ZEROBOUNCE, ORBISEARCH "
                    "or MYEMAILVERIFIER) in .env",
                    file=sys.stderr,
                )
                return 2
            print(
                f"{len(contacts)} contacts | finders {sorted(finders)} | verifiers "
                f"{sorted(verifiers)} | resolvers {sorted(resolvers)}"
            )
            collect(
                contacts,
                finders,
                verifiers,
                resolvers,
                matrix,
                save=lambda: matrix.save(matrix_path),
            )
    except (ProviderAuthError, BudgetExceeded) as exc:
        print(f"stopped: {exc}", file=sys.stderr)
        return 1
    finally:
        matrix.save(matrix_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
