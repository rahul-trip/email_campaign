"""The review queue: read in a fixed number of queries, best-first on request, with a hot count.

It used to read a few rows for every waiting email; the database is a network away, so a queue
of 44 took 11 seconds to open on the first page of the app.
"""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.engine import Engine

from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.actors import SYSTEM
from outbound.services.review import ReviewService
from tests.db.test_review_and_deliver import copy_ready


def waiting(
    factory: UnitOfWorkFactory, ws: str, domains: list[str], fits: list[int | None]
) -> dict[str, str]:
    """An email waiting for each domain, its lead scoring the matching fit: {domain: message id}."""
    made: dict[str, str] = {}
    for domain, fit in zip(domains, fits, strict=True):
        company_id, message_id = copy_ready(factory, ws, domain=domain)
        if fit is not None:
            with factory(ws) as uow:
                company = uow.companies.get(company_id)
                uow.companies.update_fields(
                    company_id,
                    {"fit_score": fit},
                    actor=SYSTEM,
                    expected_version=company.row_version,
                )
                uow.commit()
        made[domain] = message_id
    return made


def test_the_whole_queue_is_read_in_a_fixed_number_of_queries(
    factory: UnitOfWorkFactory, engine: Engine, ws: str
) -> None:
    statements: list[str] = []

    def count(conn: object, cursor: object, statement: str, *rest: object) -> None:
        statements.append(statement)

    waiting(factory, ws, ["a.com", "b.com"], [90, 50])
    event.listen(engine, "before_cursor_execute", count)
    try:
        statements.clear()
        ReviewService(factory, ws).queue()
        few = len(statements)
        waiting(factory, ws, [f"x{i}.com" for i in range(12)], [60] * 12)
        statements.clear()
        items = ReviewService(factory, ws).queue()
        many = len(statements)
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert len(items) == 14
    # Fourteen emails cost the same number of queries as two: nothing is read per email.
    assert many == few


def test_best_first_puts_the_best_fitting_lead_first_and_unscored_last(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    waiting(factory, ws, ["low.com", "none.com", "high.com", "mid.com"], [40, None, 95, 70])
    service = ReviewService(factory, ws)
    assert [i.company.domain for i in service.queue(best_first=True)] == [
        "high.com",
        "mid.com",
        "low.com",
        "none.com",
    ]
    assert [i.company.domain for i in service.queue(2, best_first=True)] == [
        "high.com",
        "mid.com",
    ]  # the limit keeps the best
    oldest = next(i.company.domain for i in service.queue())
    assert oldest == "low.com"  # the default is still oldest first


def test_the_items_are_the_same_as_when_read_one_at_a_time(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    made = waiting(factory, ws, ["one.com", "two.com"], [85, 30])
    service = ReviewService(factory, ws)
    by_domain = {i.company.domain: i for i in service.queue()}
    for domain, message_id in made.items():
        single = service.show(message_id).item
        assert (
            by_domain[domain] == single
        )  # the lead, the person, the address and the skipped checks


def test_the_count_of_hot_emails_waiting_only_counts_scores_above_80(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    waiting(factory, ws, ["a.com", "b.com", "c.com", "d.com"], [81, 80, 99, None])
    with factory(ws) as uow:
        assert uow.messages.count_waiting_hot() == 2
