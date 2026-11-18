"""Write the bake-off's list of known contacts from a workspace's own proven addresses.

The bake-off (``scripts/bakeoff.py``) asks each email finder to find the address of people whose
address is already known, and counts how often each is right and what it costs. It needs about
30 such people. This takes them from a workspace: people whose address a verifier proved (valid
or a settled catch-all) at their company's own domain.

    uv run python -m scripts.bakeoff_contacts --workspace quantra-energy-2 --limit 30
    uv run python -m scripts.bakeoff collect --contacts data/private/bakeoff_contacts.csv

The file holds real people's names and addresses and is written under ``data/private/``, which
git ignores. Running the bake-off sends those names, domains and addresses to the vendors it asks
(that is what a bake-off is), so only run it with vendors you have an account with.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path

from outbound.bootstrap import build_container
from outbound.config import Settings
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import WORKABLE_CONTACT_STATUSES, EmailStatus

PROVEN = (EmailStatus.VALID, EmailStatus.CATCH_ALL_RESOLVED)
DEFAULT_OUT = Path("data/private/bakeoff_contacts.csv")
COLUMNS = ("first_name", "last_name", "domain", "country", "known_email")


@dataclass(frozen=True)
class Known:
    first_name: str
    last_name: str
    domain: str
    country: str
    known_email: str


def known_contacts(factory: UnitOfWorkFactory, workspace_id: str, limit: int) -> list[Known]:
    """Up to ``limit`` people with a proven address at their company's own domain, one per
    address, a company at most once so the sample is not one company's staff."""
    found: list[Known] = []
    seen: set[str] = set()
    with factory(workspace_id) as uow:
        companies, _ = uow.companies.search(limit=200, offset=0)
        for company in companies:
            for person in uow.contacts.for_company(company.id):
                if person.status not in WORKABLE_CONTACT_STATUSES:
                    continue
                if not (person.first_name and person.last_name):
                    continue
                address = next(
                    (
                        e.email
                        for e in uow.emails.for_contact(person.id)
                        if e.email and e.status in PROVEN and e.is_primary
                    ),
                    None,
                )
                if not address or address in seen:
                    continue
                if not address.lower().endswith(f"@{company.domain.lower()}"):
                    continue  # a finder is asked for the company's own domain
                seen.add(address)
                found.append(
                    Known(
                        person.first_name,
                        person.last_name,
                        company.domain.lower(),
                        (company.country_code or "").upper(),
                        address.lower(),
                    )
                )
                break  # one person a company
            if len(found) >= limit:
                break
    return found


def write(path: Path, contacts: list[Known]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)
        for c in contacts:
            writer.writerow([c.first_name, c.last_name, c.domain, c.country, c.known_email])


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--workspace", required=True, help="the workspace's slug")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    container = build_container(Settings())
    contacts = known_contacts(container.uow, container.workspace_id(args.workspace), args.limit)
    write(args.out, contacts)
    print(f"{len(contacts)} known contacts written to {args.out} (real names and addresses: keep")
    print("it in data/private/, and run the bake-off only with vendors you have an account with).")
    return 0 if contacts else 1


if __name__ == "__main__":
    raise SystemExit(main())
