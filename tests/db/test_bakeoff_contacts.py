"""The bake-off's known contacts, taken from a workspace's proven addresses."""

from __future__ import annotations

from pathlib import Path

from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import CompanySource, ContactSource, EmailStatus, Provenance
from scripts.bakeoff import load_contacts
from scripts.bakeoff_contacts import known_contacts, write


def person(
    factory: UnitOfWorkFactory,
    ws: str,
    domain: str,
    name: tuple[str, str],
    address: str,
    status: EmailStatus,
    *,
    primary: bool = True,
) -> None:
    with factory(ws) as uow:
        company = uow.companies.create(
            domain=domain, source=CompanySource.MANUAL, country_code="gb", name=domain
        )
        contact = uow.contacts.add(
            company.id, rank=1, source=ContactSource.SITE, full_name=" ".join(name),
            first_name=name[0], last_name=name[1], title="CEO",
        )  # fmt: skip
        uow.emails.add(
            contact.id, address, Provenance.API_DATABASE, status=status, is_primary=primary
        )
        uow.commit()


def test_only_people_with_a_proven_address_at_their_own_domain_are_taken(
    factory: UnitOfWorkFactory, ws: str, tmp_path: Path
) -> None:
    person(factory, ws, "acme.com", ("Jane", "Doe"), "Jane.Doe@acme.com", EmailStatus.VALID)
    person(factory, ws, "beta.io", ("Sam", "Roe"), "sam@beta.io", EmailStatus.CATCH_ALL_RESOLVED)
    person(factory, ws, "gamma.io", ("Al", "Poe"), "al@gamma.io", EmailStatus.CATCH_ALL_UNVERIFIED)
    person(factory, ws, "delta.io", ("Bo", "Lee"), "bo@gmail.com", EmailStatus.VALID)  # not theirs
    person(factory, ws, "eps.io", ("Cy", "Kim"), "cy@eps.io", EmailStatus.VALID, primary=False)
    found = known_contacts(factory, ws, limit=30)
    assert sorted(c.known_email for c in found) == ["jane.doe@acme.com", "sam@beta.io"]
    assert {c.country for c in found} == {"GB"}

    path = tmp_path / "private" / "contacts.csv"
    write(path, found)
    loaded = load_contacts(path)  # the bake-off reads exactly what was written
    assert {(c.first_name, c.domain, c.known_email) for c in loaded} == {
        ("Jane", "acme.com", "jane.doe@acme.com"),
        ("Sam", "beta.io", "sam@beta.io"),
    }


def test_the_limit_is_respected(factory: UnitOfWorkFactory, ws: str) -> None:
    for n in range(4):
        person(factory, ws, f"c{n}.io", (f"P{n}", "Last"), f"p{n}@c{n}.io", EmailStatus.VALID)
    assert len(known_contacts(factory, ws, limit=2)) == 2
