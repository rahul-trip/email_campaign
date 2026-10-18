"""What reaches the logs: structured, complete, and free of secrets and personal data."""

from __future__ import annotations

import json
import logging

import pytest

from outbound.config import Settings
from outbound.logging import bind, clear, configure_logging, get_logger, redact


def lines(capsys: pytest.CaptureFixture[str]) -> list[dict[str, object]]:
    err = capsys.readouterr().err
    return [json.loads(line) for line in err.splitlines() if line.startswith("{")]


@pytest.fixture(autouse=True)
def json_logs() -> None:
    configure_logging("INFO", "json", "test")
    clear()


def test_a_line_is_json_with_the_standard_fields_and_bound_context(
    capsys: pytest.CaptureFixture[str],
) -> None:
    bind(run_id="r1", company_id="c1")
    get_logger("outbound.test").info("stage_done", stage="research", to_status="researched")
    [line] = lines(capsys)
    assert line["event"] == "stage_done" and line["level"] == "info"
    assert line["logger"] == "outbound.test"
    assert (line["stage"], line["to_status"]) == ("research", "researched")
    assert (line["run_id"], line["company_id"]) == ("r1", "c1")
    assert (line["service"], line["environment"]) == ("outbound", "test")
    assert str(line["timestamp"]).endswith("Z") and "version" in line


def test_a_library_that_uses_standard_logging_comes_out_in_the_same_shape(
    capsys: pytest.CaptureFixture[str],
) -> None:
    logging.getLogger("uvicorn.error").error("server said no")
    [line] = lines(capsys)
    assert line["event"] == "server said no" and line["logger"] == "uvicorn.error"
    assert line["service"] == "outbound"


def test_http_client_chatter_is_silenced_because_urls_can_hold_keys(
    capsys: pytest.CaptureFixture[str],
) -> None:
    logging.getLogger("httpx").info("HTTP Request: GET https://x.test/?api_key=abc")
    assert lines(capsys) == []


def test_below_the_configured_level_nothing_is_written(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("WARNING", "json", "test")
    get_logger("t").info("noise")
    get_logger("t").warning("signal", count=2)
    assert [(x["event"], x.get("count")) for x in lines(capsys)] == [("signal", 2)]


def test_secret_named_fields_and_email_bodies_are_never_written(
    capsys: pytest.CaptureFixture[str],
) -> None:
    get_logger("t").info(
        "x",
        password="hunter2",
        api_key="k-123",
        session_cookie="abc",
        input_tokens=412,
        body="Hi Jane, ...",
        nested={"Authorization": "Bearer abcdefghijkl", "count": 3},
    )
    [line] = lines(capsys)
    assert line["password"] == line["api_key"] == line["session_cookie"] == "[redacted]"
    assert line["input_tokens"] == 412  # a count of tokens is not a credential
    assert line["body"] == "[12 characters]"
    assert line["nested"] == {"Authorization": "[redacted]", "count": 3}


def test_email_addresses_and_keys_inside_text_are_masked() -> None:
    event = redact(
        None,
        "",
        {
            "reason": "no answer for jane.doe@acme.com at https://api.v.test/x?api_key=SECRET1&q=2",
            "header": "Bearer abcdefghijklmnop",
        },
    )
    assert (
        event["reason"]
        == "no answer for j***@acme.com at https://api.v.test/x?api_key=[redacted]&q=2"
    )
    assert event["header"] == "Bearer [redacted]"


def test_an_exception_is_structured_and_its_message_is_masked(
    capsys: pytest.CaptureFixture[str],
) -> None:
    try:
        raise ValueError("bounced: jane@acme.com")
    except ValueError:
        get_logger("t").exception("stage_failed", stage="email")
    [line] = lines(capsys)
    assert line["level"] == "error" and line["stage"] == "email"
    dumped = json.dumps(line)
    assert "ValueError" in dumped and "j***@acme.com" in dumped and "jane@acme.com" not in dumped


def test_a_terminal_gets_readable_lines_when_asked(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", "console", "test")
    get_logger("t").info("run_finished", status="succeeded", duration_ms=812)
    out = capsys.readouterr().err
    assert "run_finished" in out and "duration_ms" in out and not out.lstrip().startswith("{")


def test_a_bad_log_level_is_refused_when_settings_load(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "chatty")
    with pytest.raises(ValueError, match="log level must be one of"):
        Settings(_env_file=None)
    monkeypatch.setenv("LOG_LEVEL", "debug")
    assert Settings(_env_file=None).log_level == "DEBUG"
