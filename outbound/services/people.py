"""Find more people at a lead by role, and say what to do with them: write to their email, to their
LinkedIn, both, or just add them so the person can choose.

A search for recruiters or a head of engineering costs AI credits (searches and one model call),
so nothing here runs by itself. Each person found is added to the lead; what is done for them is
the reader's choice (``Reach``). People the search could not place at the company wait for a
person to confirm them first, and nobody is written to before that.
"""

from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.exc import IntegrityError

from outbound.db.errors import NotFound
from outbound.domain.enums import WORKABLE_CONTACT_STATUSES
from outbound.providers.errors import ProviderError
from outbound.services.leads import FreshPerson, LeadError, LeadService
from outbound.services.linkedin import LinkedInService

MAX_LEADS = 20  # one bulk request: each lead is two searches and a model call or two
PARALLEL_LEADS = 5


class Reach(StrEnum):
    NONE = "none"  # just add them to the lead; the person decides later
    EMAIL = "email"  # find their email address (a run does it)
    LINKEDIN = "linkedin"  # write a LinkedIn note and message
    BOTH = "both"


@dataclass(frozen=True)
class ReachedPerson:
    """One person found, and what was done for them."""

    contact_id: str
    name: str
    title: str | None
    linkedin_url: str | None
    confirmed: bool  # placed at the company; the rest wait for a person to confirm them
    email: str = ""  # "asked": a run looks for their address; else why not ("" when not asked)
    linkedin: str = ""  # "written": a message is ready; else why not ("" when not asked)


@dataclass(frozen=True)
class FoundForLead:
    company_id: str
    found: int = 0
    added: int = 0
    works_here: int = 0
    unsure: int = 0
    retried: bool = False
    people: tuple[ReachedPerson, ...] = ()
    email_asked: int = 0  # people whose address a run will now look for
    error: str = ""  # the search itself failed for this lead


class PeopleSearch:
    def __init__(self, leads: LeadService, linkedin: LinkedInService) -> None:
        self._leads = leads
        self._linkedin = linkedin

    def find(self, company_id: str, roles: Sequence[str], reach: Reach) -> FoundForLead:
        """Search the lead for these roles (the campaign's titles when none), add the people
        found, and do ``reach`` for those placed at the company. A failure for one person is
        recorded on that person; a failed search is recorded on the lead."""
        try:
            try:
                found = self._leads.find_people_again(company_id, roles=roles)
            except IntegrityError:  # another lead, searched at the same moment, took that profile
                found = self._leads.find_people_again(company_id, roles=roles)
        except (LeadError, ProviderError, NotFound) as error:
            return FoundForLead(company_id, error=str(error)[:300])
        people = tuple(self._reach(p, reach) for p in found.people)
        return FoundForLead(
            company_id,
            found=found.found,
            added=found.added,
            works_here=found.works_here,
            unsure=found.unsure,
            retried=found.retried,
            people=people,
            email_asked=sum(p.email == "asked" for p in people),
        )

    def find_many(
        self, company_ids: Sequence[str], roles: Sequence[str], reach: Reach
    ) -> list[FoundForLead]:
        """The same for several leads, a few at a time, in the order given."""
        ids = list(dict.fromkeys(company_ids))[:MAX_LEADS]
        with ThreadPoolExecutor(max_workers=PARALLEL_LEADS, thread_name_prefix="people") as pool:
            return list(pool.map(lambda cid: self.find(cid, roles, reach), ids))

    def _reach(self, person: FreshPerson, reach: Reach) -> ReachedPerson:
        confirmed = person.status in WORKABLE_CONTACT_STATUSES
        email = linkedin = ""
        if reach is not Reach.NONE and not confirmed:
            email = linkedin = "confirm they work here first"
        elif confirmed:
            if reach in (Reach.EMAIL, Reach.BOTH):
                email = self._ask_email(person)
            if reach in (Reach.LINKEDIN, Reach.BOTH):
                linkedin = self._write_linkedin(person)
        return ReachedPerson(
            person.contact_id,
            person.name,
            person.title,
            person.linkedin_url,
            confirmed,
            email=email,
            linkedin=linkedin,
        )

    def _ask_email(self, person: FreshPerson) -> str:
        try:
            self._leads.retry_email(person.contact_id)
        except (LeadError, NotFound) as error:
            return str(error)[:200]
        return "asked"

    def _write_linkedin(self, person: FreshPerson) -> str:
        if not person.linkedin_url:
            return "no LinkedIn profile was found for them"
        try:
            self._linkedin.write(person.contact_id)
        except (LeadError, ProviderError, NotFound) as error:
            return str(error)[:200]
        return "written"
