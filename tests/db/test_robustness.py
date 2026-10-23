"""Smaller hardening fixes: one meter, timeouts, HTTP checks, worker, run states, sync."""

from __future__ import annotations

import socket
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import Engine
from tenacity import RetryCallState, wait_none

from outbound.bootstrap import Container, container_for
from outbound.config import Settings
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.enums import (
    CallOutcome,
    CompanySource,
    ContactSource,
    MessageState,
    Provenance,
    RunKind,
    RunStatus,
)
from outbound.domain.errors import ConfigurationError
from outbound.domain.state_machines import RUN
from outbound.pipeline import build_meter, metered_search_or_none
from outbound.providers.adapters.imap_mailbox import ImapMailbox
from outbound.providers.errors import BudgetExceeded, ProviderError, RateLimited
from outbound.providers.http import HttpClient, _honouring_retry_after
from outbound.worker import Worker


def container(engine: Engine, factory: UnitOfWorkFactory, **settings: Any) -> Container:
    return container_for(Settings(_env_file=None, **settings), engine)


# ------------------------------------------------------------------ one meter, with caps


def test_a_meter_applies_the_monthly_cap_to_every_path(
    engine: Engine, factory: UnitOfWorkFactory, ws: str
) -> None:
    c = container(engine, factory, monthly_caps_micro_usd={"tavily": 10_000})
    meter = build_meter(c, ws)
    meter.record("tavily", "search", {"q": "x"}, outcome=CallOutcome.HIT, cost=10_000)
    with pytest.raises(BudgetExceeded):
        meter.call(
            provider="tavily",
            operation="search",
            request={"q": "y"},
            run=lambda: [],
            encode=lambda hits: {"items": []},
            decode=lambda stored: [],
        )


def test_the_search_used_by_intake_is_metered_with_the_same_caps(
    engine: Engine, factory: UnitOfWorkFactory, ws: str
) -> None:
    assert metered_search_or_none(container(engine, factory), ws) is None  # no key, no search
    c = container(engine, factory, tavily_api_key=SecretStr("k"))
    search = metered_search_or_none(c, ws)
    assert search is not None and type(search).__name__ == "MeteredSearch"


def test_a_meter_for_a_missing_workspace_says_what_is_wrong(
    engine: Engine, factory: UnitOfWorkFactory
) -> None:
    with pytest.raises(ConfigurationError, match="does not exist"):
        build_meter(container(engine, factory), "no-such-workspace")


# ------------------------------------------------------------------ IMAP timeout


def test_the_mailbox_connection_has_a_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake(address: tuple[str, int], timeout: float | None = None) -> socket.socket:
        seen["timeout"] = timeout
        raise OSError("stop here")

    monkeypatch.setattr(socket, "create_connection", fake)
    box = ImapMailbox(
        host="imap.customer.example",
        address="a@b.com",
        password="p",
        timeout=12.5,
        resolve=lambda host, port: ["93.184.216.34"],
    )
    with pytest.raises(ProviderError):
        box.list_sent(datetime.now(UTC))
    assert seen["timeout"] == 12.5


# ------------------------------------------------------------------ HTTP


def test_an_answer_that_is_not_a_json_object_is_a_provider_error() -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[1, 2])))
    http = HttpClient("vendor", "https://v.test", client=client)
    with pytest.raises(ProviderError, match="expected a JSON object"):
        http.get_object("/x")
    with pytest.raises(ProviderError, match="expected a JSON object"):
        http.post_object("/x", {})


def _state_after(error: Exception) -> RetryCallState:
    state = RetryCallState(retry_object=None, fn=None, args=(), kwargs={})  # type: ignore[arg-type]
    state.set_exception((type(error), error, None))
    return state


def test_a_rate_limit_waits_as_long_as_the_vendor_asked_up_to_a_minute() -> None:
    wait = _honouring_retry_after(wait_none())
    assert wait(_state_after(RateLimited("v", retry_after=7))) == 7
    assert wait(_state_after(RateLimited("v", retry_after=900))) == 60
    assert wait(_state_after(RateLimited("v"))) == 0  # no hint: the normal back-off
    assert wait(_state_after(ProviderError("v", "boom", retryable=True))) == 0


# ------------------------------------------------------------------ worker


def test_the_worker_outlives_a_database_error(
    engine: Engine, factory: UnitOfWorkFactory, ws: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = Worker(container(engine, factory), lambda _ws: None, tick_every=None)  # type: ignore[arg-type,return-value]
    calls = {"n": 0}

    def flaky() -> list[object]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database is locked")
        return []

    monkeypatch.setattr(worker, "plan", flaky)
    worker.run_forever(poll_seconds=0, stop=lambda: calls["n"] >= 3)
    assert calls["n"] == 3  # it kept going after the first call blew up


# ------------------------------------------------------------------ run states


def test_runs_only_move_forward() -> None:
    assert RUN.allows(RunStatus.QUEUED, RunStatus.RUNNING)
    assert RUN.allows(RunStatus.RUNNING, RunStatus.SUCCEEDED)
    for final in (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED):
        assert RUN.is_final(final)
    assert not RUN.allows(RunStatus.SUCCEEDED, RunStatus.FAILED)


def test_a_finished_run_is_not_rewritten_by_a_later_report(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        run_id = uow.runs.start(RunKind.PIPELINE, {})
        uow.runs.finish(run_id, RunStatus.SUCCEEDED, {"research": {"advanced": 1}})
        uow.runs.finish(run_id, RunStatus.FAILED, {"error": "reported too late"})
        assert uow.runs.cancel(run_id) is RunStatus.SUCCEEDED
        assert uow.runs.status(run_id) is RunStatus.SUCCEEDED


# ------------------------------------------------------------------ Sent sync


def test_old_workbook_messages_never_crowd_out_real_drafts(
    factory: UnitOfWorkFactory, ws: str
) -> None:
    with factory(ws) as uow:
        company = uow.companies.create(domain="legacy.com", source=CompanySource.IMPORT)
        contact = uow.contacts.add(company.id, rank=1, source=ContactSource.OPERATOR)
        address = uow.emails.add(contact.id, "a@legacy.com", Provenance.OPERATOR_GIVEN)
        uow.messages.create(
            company_id=company.id,
            contact_id=contact.id,
            contact_email_id=address.id,
            step=0,
            subject="s",
            generated_body="b",
            state=MessageState.DRAFTED,
        )
        uow.commit()
        assert uow.messages.drafted_in_mailbox(500) == []
