"""Check each configured vendor against the real service, using your own address.

    uv run python -m scripts.live_check --address you@yours.com           # every vendor; asks
    uv run python -m scripts.live_check --address you@yours.com --only tavily --yes
    uv run python -m scripts.live_check --address you@yours.com --workspace acme   # + its mailboxes

It costs a few cents (one verification per verifier, one search, one model reply) and the mailbox
check saves one draft and deletes it again. Only your own address is ever sent to a vendor. Keys
and passwords are never printed. Finders are left out unless you pass ``--finders`` because they
search for a person and use credits.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

from outbound.config import Settings
from outbound.providers import registry
from outbound.providers.ports import OutgoingDraft, PersonQuery

REGISTRY_PROBE = "Octopus Energy"  # a well-known UK company, to see that Companies House answers


@dataclass(frozen=True)
class Result:
    name: str
    ok: bool
    detail: str
    seconds: float


Check = Callable[[], str]


def _mailbox_checks(settings: Settings, workspace: str, address: str) -> dict[str, Check]:
    """One check per mailbox the workspace connected: save a draft to ``address``, find it,
    delete it."""
    from outbound.bootstrap import build_container
    from outbound.pipeline import mailboxes_for
    from outbound.stages.mailboxes import StoredMailboxes

    container = build_container(settings)
    workspace_id = container.workspace_id(workspace)
    mailboxes = mailboxes_for(container, workspace_id)
    assert isinstance(mailboxes, StoredMailboxes)
    with container.uow(workspace_id) as uow:
        views = uow.mailboxes.all()
    checks: dict[str, Check] = {}
    for view in views:

        def check(view=view) -> str:  # type: ignore[no-untyped-def]  # bound per loop turn
            mailbox = mailboxes.build(view)
            draft = OutgoingDraft(
                to_address=address,
                subject="Outbound live check (safe to delete)",
                body="Saved by scripts/live_check.py and deleted straight away.",
                message_id=f"<live-check-{int(time.time())}@{view.sending_domain}>",
            )
            ref = mailbox.append_draft(draft)
            try:
                found = mailbox.draft_exists(ref)
            finally:
                removed = mailbox.delete_draft(ref)
            return f"{view.gateway.value}: draft saved, found={found}, deleted={removed}"

        checks[f"mailbox:{view.address}"] = check
    return checks


def _checks(settings: Settings, address: str, *, finders: bool) -> dict[str, Check]:
    checks: dict[str, Check] = {}

    if settings.llm_model and (
        settings.llm_api_key.get_secret_value() or settings.copilot_api_key.get_secret_value()
    ):

        def llm() -> str:
            reply = registry.build_llm(settings).complete(
                "Reply with the single word: ready", "ping"
            )
            model = f"{settings.llm_provider}/{settings.llm_model}"
            return f"{model} answered ({len(reply.text)} characters)"

        checks["llm"] = llm

    if settings.tavily_api_key.get_secret_value():

        def tavily() -> str:
            search = registry.build_search(settings)
            plain = search.search("Octopus Energy", max_results=2)
            scoped = search.search("site:octopus.energy about", max_results=2)
            pages = search.extract([plain[0].url]) if plain else []
            return (
                f"search {len(plain)} hits; site: search {len(scoped)} hits; "
                f"extract {len(pages)} page(s)"
            )

        checks["tavily"] = tavily

    companies_house = registry.build_company_registry(settings)
    if companies_house is not None:

        def house() -> str:
            entries = companies_house.search(REGISTRY_PROBE, max_results=3)
            return f"{len(entries)} match(es); first: {entries[0].name if entries else 'none'}"

        checks["companies_house"] = house

    for name, verifier in registry.configured_verifiers(settings).items():

        def verify(v=verifier) -> str:  # type: ignore[no-untyped-def]  # bound per loop turn
            result = v.verify(address)
            return (
                f"{result.status.value} (vendor said {result.raw_status!r}, billed={result.billed})"
            )

        checks[f"verify:{name}"] = verify

    for name, resolver in registry.configured_resolvers(settings).items():

        def resolve(r=resolver) -> str:  # type: ignore[no-untyped-def]
            ticket = r.submit(address)
            outcome = ticket.result or r.poll(ticket)
            state = (
                outcome.status.value if outcome else "still pending (normal for an async vendor)"
            )
            return f"submitted, ref {ticket.ref[:8]}…, {state}"

        checks[f"resolve:{name}"] = resolve

    if finders:
        for name, finder in registry.configured_finders(settings).items():

            def find(f=finder) -> str:  # type: ignore[no-untyped-def]
                result = f.find(
                    PersonQuery(first_name="Greg", last_name="Jackson"), "octopus.energy"
                )
                return f"found={result.email is not None}"

            checks[f"find:{name}"] = find

    return checks


def run(checks: dict[str, Check]) -> list[Result]:
    results: list[Result] = []
    for name, check in checks.items():
        started = time.monotonic()
        try:
            results.append(Result(name, True, check(), time.monotonic() - started))
        except Exception as error:  # a check must never stop the others
            results.append(
                Result(
                    name,
                    False,
                    f"{type(error).__name__}: {error}"[:300],
                    time.monotonic() - started,
                )
            )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--only", help="comma-separated checks, for example imap,llm,verify:zerobounce"
    )
    parser.add_argument(
        "--address", required=True, help="your own address: verified, and drafts are saved to it"
    )
    parser.add_argument("--workspace", help="also check the mailboxes this workspace connected")
    parser.add_argument(
        "--finders", action="store_true", help="also try the email finders (uses credits)"
    )
    parser.add_argument("--yes", action="store_true", help="do not ask first")
    args = parser.parse_args()

    settings = Settings()
    address = args.address
    checks = _checks(settings, address, finders=args.finders)
    if args.workspace:
        checks.update(_mailbox_checks(settings, args.workspace, address))
    if args.only:
        wanted = {n.strip() for n in args.only.split(",")}
        unknown = wanted - set(checks)
        if unknown:
            print(f"not configured or unknown: {sorted(unknown)}; available: {sorted(checks)}")
            return 2
        checks = {n: c for n, c in checks.items() if n in wanted}

    print(f"Will check {len(checks)}: {', '.join(checks)}")
    print(f"Only {address} is sent to vendors. Expect a few US cents in total.")
    if not args.yes and input("Go ahead? [y/N] ").strip().lower() != "y":
        return 1

    results = run(checks)
    width = max(len(r.name) for r in results)
    for r in results:
        print(f"{'ok  ' if r.ok else 'FAIL'}  {r.name:<{width}}  {r.seconds:5.1f}s  {r.detail}")
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
