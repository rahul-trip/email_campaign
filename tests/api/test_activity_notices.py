"""The bell tells a workspace's people what the engine did, without piling up lines."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from outbound.bootstrap import Container
from outbound.db.models import CompanyRow
from outbound.db.types import utcnow
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import CompanySource, EntityType, NotificationKind, RunKind, RunStatus
from outbound.services.activity_notices import ActivityNotifier
from outbound.worker import Worker, workspace_names
from tests.api.conftest import Api


def notifier(container: Container) -> ActivityNotifier:
    return ActivityNotifier(container.uow, container.identity, workspace_names(container))


def finished_run(
    factory: UnitOfWorkFactory, ws: str, domain: str, score: int, *, to: str = "copy_ready"
) -> tuple[str, str]:
    """A run that moved one lead to ``to``. Returns the run's and the lead's ids."""
    with factory(ws) as uow:
        run_id = uow.runs.start(RunKind.PIPELINE, {})
        company = uow.companies.create(domain=domain, source=CompanySource.MANUAL)
        uow.session.get(CompanyRow, company.id).fit_score = score  # type: ignore[union-attr]
        uow.events.append(
            EntityType.COMPANY,
            company.id,
            "status_changed",
            "system",
            {"from": "email_ready", "to": to, "run_id": run_id},
        )
        uow.runs.finish(run_id, RunStatus.SUCCEEDED, {})
        uow.commit()
    return run_id, company.id


def items(api: Api) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = api.get("/api/me/notifications").json()["items"]
    return found


def of(api: Api, kind: str) -> list[dict[str, Any]]:
    return [n for n in items(api) if n["kind"] == kind]


def test_a_run_that_wrote_drafts_tells_everyone_once_and_updates_the_line(
    api: Api, container: Container, factory: UnitOfWorkFactory, ws: str
) -> None:
    first, _ = finished_run(factory, ws, "a.com", 60)
    second, _ = finished_run(factory, ws, "b.com", 60)
    tell = notifier(container)
    tell.after_run(ws, first, by_person=False)
    tell.after_run(ws, second, by_person=False)
    [line] = of(api, "drafts_ready")
    assert line["data"]["drafts"] == 2 and line["data"]["hot"] == 0
    assert line["data"]["workspace_name"] and line["data"]["slug"]


def test_a_hot_lead_is_announced_once_however_often_it_is_seen(
    api: Api, container: Container, factory: UnitOfWorkFactory, ws: str
) -> None:
    run_id, company_id = finished_run(factory, ws, "hot.com", 92)
    tell = notifier(container)
    tell.after_run(ws, run_id, by_person=False)
    api.post("/api/me/notifications/read", json={"id": None})  # read, so a repeat would add a row
    tell.after_run(ws, run_id, by_person=False)
    [hot] = of(api, "hot_lead")
    assert hot["data"]["company_id"] == company_id and hot["data"]["fit"] == 92


def test_a_quiet_run_says_nothing_unless_a_person_started_it(
    api: Api, container: Container, factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        quiet = uow.runs.start(RunKind.PIPELINE, {})
        uow.runs.finish(quiet, RunStatus.SUCCEEDED, {})
        uow.commit()
    tell = notifier(container)
    tell.after_run(ws, quiet, by_person=False)
    assert items(api) == []
    tell.after_run(ws, quiet, by_person=True)
    [done] = of(api, "run_finished")
    assert done["data"]["run_id"] == quiet and done["data"]["drafts"] == 0


def test_a_failed_run_and_a_paused_discovery_are_told(
    api: Api, container: Container, factory: UnitOfWorkFactory, ws: str
) -> None:
    tell = notifier(container)
    tell.run_failed(ws, "run-1", "ProviderError: down")
    tell.discovery_paused(ws, 52, 50)
    api.post("/api/me/notifications/read", json={"id": None})
    tell.discovery_paused(ws, 53, 50)  # said at most once a day, even when read
    assert of(api, "run_failed")[0]["data"]["reason"] == "ProviderError: down"
    assert len(of(api, "discovery_paused")) == 1


def test_old_notifications_are_pruned(
    api: Api, container: Container, factory: UnitOfWorkFactory, ws: str
) -> None:
    tell = notifier(container)
    tell.run_failed(ws, "run-1", "x")
    assert len(items(api)) == 1
    with container.identity() as ids:
        ids.notifications.prune(utcnow() + timedelta(days=1))
        ids.commit()
    assert items(api) == []


def test_a_failing_notifier_never_fails_the_worker(container: Container, ws: str) -> None:
    class Broken:
        def after_run(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("the bell is broken")

    worker = Worker(container, lambda _ws: None, tick_every=None, notifier=Broken())  # type: ignore[arg-type,return-value]
    worker._notify(ws, lambda n: n.after_run(ws, "run", by_person=True))


def test_every_kind_the_notifier_writes_is_a_known_kind() -> None:
    assert {k.value for k in NotificationKind} >= {
        "drafts_ready", "hot_lead", "needs_attention", "auto_approved",
        "run_finished", "run_failed", "discovery_paused", "account",
    }  # fmt: skip
