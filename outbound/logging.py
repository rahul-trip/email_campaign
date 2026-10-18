"""Structured logging for the whole application, in one place.

Every line is one JSON object on stderr (or, on a terminal, a readable coloured line), whether it
came from our code or from a library such as uvicorn, SQLAlchemy or httpx, so a log collector
needs one parser. Each line carries ``timestamp`` (UTC, ISO 8601), ``level``, ``logger``,
``event``, ``service``, ``version`` and ``environment``, plus whatever was bound with ``bind``
(``request_id``, ``run_id``, ``workspace_id``, ``company_id``, ...).

Nothing sensitive may reach a log line. A processor runs on every record and:

* replaces the value of any field named like a secret (password, token, api key, cookie, ...);
* replaces email-body fields with their length;
* masks email addresses wherever they appear in text, including exception messages;
* masks API keys, tokens and passwords that appear in URLs or ``Authorization`` values.

Log events, not sentences: ``log.info("run_finished", status="succeeded", duration_ms=812)``.
Put ids and counts in fields; never put a person's name, address or an email's text in one.
"""

from __future__ import annotations

import io
import logging
import re
import sys
from importlib import metadata
from typing import Any, TextIO, cast

import structlog
from structlog.typing import EventDict, Processor

SERVICE = "outbound"
LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

# A field whose name contains one of these has its value replaced, whatever it holds.
SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "session",
)
# Fields that hold an email's text: only the length is logged.
BODY_KEYS = frozenset({"body", "email_body", "generated_body", "final_body", "edited_body"})
REDACTED = "[redacted]"

_EMAIL = re.compile(r"\b([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
_SECRET_IN_URL = re.compile(
    r"(?i)\b((?:api[_-]?key|apikey|key|token|access[_-]?token|secret|password|passwd)=)[^&\s\"']+"
)
_AUTH_VALUE = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
_MAX_DEPTH = 8

# Libraries that log too much, or log things (full URLs with keys in them) we must not print.
_QUIET = {
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
    "urllib3": logging.WARNING,
    "asyncio": logging.WARNING,
    "sqlalchemy.engine": logging.WARNING,
    "alembic": logging.WARNING,  # keeps the CLI output clean
    "multipart": logging.WARNING,
    "langchain_core": logging.WARNING,
    "langgraph": logging.WARNING,
    "watchfiles": logging.WARNING,
}


class _CurrentStderr(io.TextIOBase):
    """A file-like that writes to whatever ``sys.stderr`` is at the moment of writing.

    The handler would otherwise keep the stream that existed when logging was configured. If
    that stream is later closed (a test runner, a redirected command), every log line would raise.
    """

    def write(self, s: str, /) -> int:
        return sys.stderr.write(s)

    def flush(self) -> None:
        sys.stderr.flush()

    def isatty(self) -> bool:
        return sys.stderr.isatty()


# ------------------------------------------------------------------ redaction


def _mask_text(text: str) -> str:
    text = _EMAIL.sub(lambda m: f"{m.group(1)}***@{m.group(2)}", text)
    text = _SECRET_IN_URL.sub(lambda m: f"{m.group(1)}{REDACTED}", text)
    return _AUTH_VALUE.sub(lambda m: f"{m.group(1)} {REDACTED}", text)


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    if lowered.endswith("tokens"):  # input_tokens, output_tokens: counts, not credentials
        return False
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def _clean(value: Any, depth: int = 0) -> Any:
    if isinstance(value, str):
        return _mask_text(value)
    if depth >= _MAX_DEPTH:
        return value
    if isinstance(value, dict):
        return {k: _clean_field(str(k), v, depth + 1) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_clean(v, depth + 1) for v in value]
    return value


def _clean_field(key: str, value: Any, depth: int = 0) -> Any:
    if _is_sensitive_key(key):
        return REDACTED
    if key.lower() in BODY_KEYS and isinstance(value, str):
        return f"[{len(value)} characters]"
    return _clean(value, depth)


def redact(_logger: Any, _method: str, event_dict: EventDict) -> EventDict:
    """The processor that keeps secrets and personal data out of every log line."""
    return {key: _clean_field(key, value) for key, value in event_dict.items()}


# ------------------------------------------------------------------ configuration


_LEAD_KEYS = ("timestamp", "level", "logger", "event")


def _lead_with_standard_keys(_logger: Any, _method: str, event_dict: EventDict) -> EventDict:
    """Put timestamp, level, logger and event first, so a line reads left to right."""
    first = {key: event_dict[key] for key in _LEAD_KEYS if key in event_dict}
    return {**first, **{k: v for k, v in event_dict.items() if k not in first}}


def _version() -> str:
    try:
        return metadata.version(SERVICE)
    except metadata.PackageNotFoundError:
        return "unknown"


def _service_fields(environment: str) -> Processor:
    fixed = {"service": SERVICE, "version": _version(), "environment": environment}

    def add(_logger: Any, _method: str, event_dict: EventDict) -> EventDict:
        for key, value in fixed.items():
            event_dict.setdefault(key, value)
        return event_dict

    return add


def normalise_level(level: str) -> str:
    """``level`` in upper case, or a ValueError naming the allowed ones."""
    upper = level.strip().upper()
    if upper not in LEVELS:
        raise ValueError(f"log level must be one of {', '.join(LEVELS)} (got {level!r})")
    return upper


def configure_logging(
    level: str = "INFO", fmt: str = "auto", environment: str = "development"
) -> None:
    """Route everything through structlog. Safe to call more than once.

    ``fmt`` is ``json``, ``console`` or ``auto`` (console on a terminal, JSON otherwise, which
    is what a container or a service manager sees).
    """
    level = normalise_level(level)
    as_json = fmt == "json" or (fmt == "auto" and not sys.stderr.isatty())

    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        _service_fields(environment),
    ]
    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if as_json
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )
    exceptions: Processor = (
        structlog.processors.dict_tracebacks if as_json else structlog.processors.format_exc_info
    )

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *shared,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )

    handler = logging.StreamHandler(cast(TextIO, _CurrentStderr()))
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                exceptions,
                redact,
                _lead_with_standard_keys,
                renderer,
            ],
        )
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for name, quiet in _QUIET.items():
        logging.getLogger(name).setLevel(max(quiet, logging.getLevelNamesMapping()[level]))
    # uvicorn's own access line would print the raw URL; the request middleware logs instead.
    logging.getLogger("uvicorn.access").disabled = True


def get_logger(name: str = SERVICE) -> structlog.stdlib.BoundLogger:
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))


bind = structlog.contextvars.bind_contextvars
unbind = structlog.contextvars.unbind_contextvars
clear = structlog.contextvars.clear_contextvars
bound = structlog.contextvars.bound_contextvars
