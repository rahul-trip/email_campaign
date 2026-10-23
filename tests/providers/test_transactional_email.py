"""The platform's own email (Phase 6b): SMTP through a relay, or the log in development."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any, ClassVar

import pytest

from outbound.config import Settings
from outbound.domain.errors import ConfigurationError
from outbound.providers.adapters.transactional_email import LogEmail, SmtpEmail
from outbound.providers.errors import ProviderError
from outbound.providers.ports import OutgoingEmail
from outbound.providers.registry import build_transactional_email

MESSAGE = OutgoingEmail(to="pat@customer.example", subject="Hello", text="A link")


class FakeSmtp:
    instances: ClassVar[list[FakeSmtp]] = []

    def __init__(self, host: str, port: int, timeout: float, **_: Any) -> None:
        self.host, self.port, self.timeout = host, port, timeout
        self.calls: list[str] = []
        self.sent: list[EmailMessage] = []
        FakeSmtp.instances.append(self)

    def __enter__(self) -> FakeSmtp:
        return self

    def __exit__(self, *_: object) -> None:
        self.calls.append("quit")

    def starttls(self, context: object) -> None:
        self.calls.append("starttls")

    def login(self, username: str, password: str) -> None:
        self.calls.append(f"login:{username}")

    def send_message(self, message: EmailMessage) -> None:
        self.sent.append(message)


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeSmtp.instances.clear()
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSmtp)


def test_smtp_sends_over_tls_after_signing_in() -> None:
    SmtpEmail("smtp.relay.example", 587, "key", "secret", "Outbound <no-reply@x.example>").send(
        MESSAGE
    )
    [smtp] = FakeSmtp.instances
    assert smtp.calls == ["starttls", "login:key", "quit"]
    [sent] = smtp.sent
    assert (sent["To"], sent["Subject"]) == ("pat@customer.example", "Hello")
    assert sent["From"] == "Outbound <no-reply@x.example>" and "A link" in sent.get_content()
    assert smtp.timeout > 0


def test_port_465_is_tls_from_the_start() -> None:
    SmtpEmail("smtp.relay.example", 465, "", "", "x@x.example").send(MESSAGE)
    [smtp] = FakeSmtp.instances
    assert "starttls" not in smtp.calls and len(smtp.sent) == 1


def test_a_relay_failure_is_a_provider_error_without_the_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(self: FakeSmtp, message: EmailMessage) -> None:
        raise smtplib.SMTPRecipientsRefused({"pat@customer.example": (550, b"no")})

    monkeypatch.setattr(FakeSmtp, "send_message", refuse)
    with pytest.raises(ProviderError) as raised:
        SmtpEmail("smtp.relay.example", 587, "", "", "x@x.example").send(MESSAGE)
    assert "pat@customer.example" not in str(raised.value)


def test_without_smtp_development_logs_and_production_refuses_to_start() -> None:
    assert isinstance(build_transactional_email(Settings(_env_file=None)), LogEmail)
    assert isinstance(
        build_transactional_email(Settings(_env_file=None, smtp_host="smtp.relay.example")),
        SmtpEmail,
    )
    with pytest.raises(ConfigurationError):
        build_transactional_email(Settings(_env_file=None, environment="production"))


def test_the_log_keeps_what_it_would_have_sent() -> None:
    outbox = LogEmail()
    outbox.send(MESSAGE)
    assert outbox.sent == [MESSAGE]
