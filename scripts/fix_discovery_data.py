"""Clean up the leads from the first discovery run (2026-10-19), now that the causes are fixed.

What it changes, each through the same services the app uses, so every change writes its event:

1. Discovered leads named after an article's headline get the company's own name (written as
   the engine, so it is not marked as yours and research may refine it later).
2. People a LinkedIn search attached to the wrong company are removed.
3. "tata power" was taken to the group's tata.com: tatapower.com is added as Tata Power, and
   the tata.com lead is deleted.
4. On rebase.energy the draft went to the CTO; it is moved to the CEO you gave consent for.

Nothing is written without ``--apply``: by default it prints what it would do. Each step looks
the lead up by domain and the person by name, and skips itself when there is nothing left to
do, so running it twice is harmless.

    uv run python -m scripts.fix_discovery_data                       # see the plan
    uv run python -m scripts.fix_discovery_data --apply               # do it
    uv run python -m scripts.fix_discovery_data --apply --rerun-research
        # also send amperon.co back to research so the fixed people search runs (a few cents)
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass

from outbound.bootstrap import build_container
from outbound.config import Settings
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.actors import OPERATOR, SYSTEM
from outbound.domain.entities import Company, Contact
from outbound.domain.enums import CompanySource, CompanyStatus, ContactSource, ImportSource
from outbound.domain.names import same_person
from outbound.services import defaults
from outbound.services.intake import IntakeService
from outbound.services.leads import LeadService
from outbound.services.privacy import PrivacyService

# The name each discovered company calls itself on its own site (from the stored research).
NAMES = {
    "amperon.co": "Amperon",
    "ltm.com": "LTIMindtree",
    "bankofamerica.com": "Bank of America",
    "aleasoft.com": "AleaSoft",
    "ifs.com": "IFS",
    "utilityserviceprovider.com": "Maverick Corporation",
    "enverus.com": "Enverus",
    "volue.com": "Volue",
}
# People a LinkedIn search placed at a company they do not work for.
WRONG_PEOPLE = {
    "amperon.co": ("Del Misenheimer", "Dan Roth"),
    "ltm.com": ("Sarah DaVanzo", "Austin Wignall"),
    "utilityserviceprovider.com": ("Adam Shaw", "Jigar Shah"),
}
WRONG_DOMAIN, RIGHT_DOMAIN, RIGHT_NAME = "tata.com", "tatapower.com", "Tata Power"
RECIPIENT_DOMAIN, RECIPIENT = "rebase.energy", "Sebastian Haglund"
RERUN = ("amperon.co",)


@dataclass(frozen=True)
class Action:
    what: str
    do: Callable[[], object]


def _company(factory: UnitOfWorkFactory, ws: str, domain: str) -> Company | None:
    with factory(ws) as uow:
        return uow.companies.by_domain(domain)


def _people(factory: UnitOfWorkFactory, ws: str, company_id: str) -> list[Contact]:
    with factory(ws) as uow:
        return uow.contacts.for_company(company_id)


def plan(factory: UnitOfWorkFactory, ws: str, *, rerun_research: bool = False) -> list[Action]:
    leads = LeadService(factory, ws)
    actions: list[Action] = []

    for domain, name in NAMES.items():
        company = _company(factory, ws, domain)
        if company is None or company.source is not CompanySource.DISCOVERY:
            continue
        if company.name == name or "name" in company.manual_fields:
            continue

        def rename(company: Company = company, name: str = name) -> None:
            with factory(ws) as uow:
                current = uow.companies.get(company.id)
                uow.companies.update_fields(
                    company.id, {"name": name}, actor=SYSTEM, expected_version=current.row_version
                )
                uow.commit()

        actions.append(Action(f"{domain}: rename {company.name!r} to {name!r}", rename))

    for domain, names in WRONG_PEOPLE.items():
        company = _company(factory, ws, domain)
        if company is None:
            continue
        for person in _people(factory, ws, company.id):
            wrong = any(same_person(person.full_name, n) for n in names)
            if wrong and person.source is ContactSource.SEARCH:

                def remove(person: Contact = person) -> None:
                    leads.remove_person(person.id, actor=OPERATOR)

                actions.append(
                    Action(
                        f"{domain}: remove {person.full_name} (a search matched them by mistake)",
                        remove,
                    )
                )

    wrong_lead = _company(factory, ws, WRONG_DOMAIN)
    if wrong_lead is not None and _company(factory, ws, RIGHT_DOMAIN) is None:

        def move_tata(lead: Company = wrong_lead) -> None:
            IntakeService(factory, ws, None).run(
                [{"website": RIGHT_DOMAIN, "company": RIGHT_NAME, "country": lead.country_code}],
                source=ImportSource.CLI,
                campaign_id=lead.campaign_id,
            )
            PrivacyService(factory, ws).delete_lead(lead.id, confirm_domain=WRONG_DOMAIN)

        actions.append(
            Action(
                f"add {RIGHT_DOMAIN} as {RIGHT_NAME!r} (country {wrong_lead.country_code}),"
                f" then delete the {WRONG_DOMAIN} lead ({wrong_lead.status.value})",
                move_tata,
            )
        )

    rebase = _company(factory, ws, RECIPIENT_DOMAIN)
    if rebase is not None:
        people = _people(factory, ws, rebase.id)
        chosen = next((p for p in people if same_person(p.full_name, RECIPIENT)), None)
        with factory(ws) as uow:
            live = [
                m
                for m in uow.messages.for_company(rebase.id)
                if m.state.value in ("generated", "approved")
            ]
        if chosen is not None and live and live[0].contact_id != chosen.id:
            actions.append(
                Action(
                    f"{RECIPIENT_DOMAIN}: cancel the email to the CTO and write to {RECIPIENT}"
                    " (whose address and consent you gave)",
                    lambda: leads.change_recipient(rebase.id, chosen.id, actor=OPERATOR),
                )
            )

    if rerun_research:
        for domain in RERUN:
            company = _company(factory, ws, domain)
            if company is None or company.status is not CompanyStatus.FAILED:
                continue

            def rerun(company: Company = company) -> None:
                with factory(ws) as uow:
                    uow.companies.transition(
                        company.id,
                        CompanyStatus.NEW,
                        expected_version=uow.companies.get(company.id).row_version,
                        actor=OPERATOR,
                        reason="research again with the fixed people search",
                    )
                    uow.commit()

            actions.append(
                Action(f"{domain}: research again (the next run; a few Tavily credits)", rerun)
            )
    return actions


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--apply", action="store_true", help="make the changes (default: show)")
    parser.add_argument(
        "--rerun-research", action="store_true", help="also research amperon.co again"
    )
    parser.add_argument("--workspace", default=defaults.DEFAULT_WORKSPACE_NAME)
    args = parser.parse_args()

    container = build_container(Settings())
    ws = container.workspace_id(args.workspace)
    actions = plan(container.uow, ws, rerun_research=args.rerun_research)
    if not actions:
        print("Nothing to do: the data is already clean.")
        return 0
    for number, action in enumerate(actions, start=1):
        print(f"{number}. {action.what}")
    if not args.apply:
        print("\nNothing was changed. Run again with --apply to make these changes.")
        return 0
    for action in actions:
        action.do()
        print(f"done: {action.what}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
