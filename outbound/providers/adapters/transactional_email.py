"""The platform's own email: SMTP through any provider's relay, or the log in development.

Postmark, Resend and Amazon SES all offer an SMTP relay, so one adapter fits whichever the team
chooses. Without SMTP settings (development, tests) messages are written to the log instead,
so the invitation and reset links can still be followed on a laptop.
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from outbound.logging import get_logger
from outbound.providers.errors import ProviderError
from outbound.providers.ports import OutgoingEmail

log = get_logger(__name__)


class SmtpEmail:
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        sender: str,
        *,
        timeout: float = 20.0,
    ) -> None:
        self._host, self._port = host, port
        self._username, self._password = username, password
        self._sender, self._timeout = sender, timeout

    def send(self, email: OutgoingEmail) -> None:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = email.to
        message["Subject"] = email.subject
        message.set_content(email.text)
        try:
            if self._port == 465:
                with smtplib.SMTP_SSL(
                    self._host, self._port, timeout=self._timeout,
                    context=ssl.create_default_context(),
                ) as smtp:  # fmt: skip
                    self._deliver(smtp, message)
            else:
                with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as smtp:
                    smtp.starttls(context=ssl.create_default_context())
                    self._deliver(smtp, message)
        except (OSError, smtplib.SMTPException) as error:
            raise ProviderError("smtp", f"sending failed: {type(error).__name__}") from None

    def _deliver(self, smtp: smtplib.SMTP, message: EmailMessage) -> None:
        if self._username:
            smtp.login(self._username, self._password)
        smtp.send_message(message)


class LogEmail:
    """Development only: the message goes to the log, never to anyone."""

    def __init__(self) -> None:
        self.sent: list[OutgoingEmail] = []

    def send(self, email: OutgoingEmail) -> None:
        self.sent.append(email)
        log.warning("email_not_sent", reason="no SMTP settings", subject=email.subject)
        print(f"\n--- email (not sent; no SMTP settings) ---\n{email.text}\n---\n")
