"""Classifying incoming mail by rule (Phase 4a): three or more samples per category."""

from __future__ import annotations

import pytest

from outbound.domain.enums import InboundCategory as C
from outbound.domain.inbox import classify

HARD = [
    (
        "MAILER-DAEMON@mail.example.org",
        "Undelivered Mail Returned to Sender",
        "This is the mail system.\nFinal-Recipient: rfc822; Jane.Doe@acme.co.uk\n"
        "Action: failed\nStatus: 5.1.1\nDiagnostic-Code: smtp; 550 5.1.1 user unknown",
    ),
    (
        "postmaster@acme.co.uk",
        "Delivery Status Notification (Failure)",
        "Your message wasn't delivered to jane@acme.co.uk because the address couldn't be found.\n"
        "The response was: 550 5.1.1 The email account does not exist.",
    ),
    (
        "mailer-daemon@googlemail.com",
        "Mail delivery failed: returning message to sender",
        "Message could not be delivered to the following recipient:\n"
        "<j.doe@acme.co.uk>\nremote server said: 5.4.1 recipient address rejected",
    ),
]
SOFT = [
    (
        "MAILER-DAEMON@mail.example.org",
        "Delivery Status Notification (Delay)",
        "Final-Recipient: rfc822; sam@acme.com\nStatus: 4.2.2\nDiagnostic-Code: mailbox full",
    ),
    (
        "postmaster@acme.com",
        "Undeliverable: hello",
        "Delivery has failed temporarily for sam@acme.com. Status 4.4.7 message expired.",
    ),
    (
        "mailer-daemon@x.example",
        "Returned mail: see transcript for details",
        "Failed: sam@acme.com\n451 4.7.1 try again later",
    ),
]
OPT_OUT = [
    ("a@acme.com", "Re: Quick question", "Please unsubscribe me from this list.\n\n> Hi Alex,"),
    ("b@acme.com", "Re: Quick question", "Remove me from your mailing list. Thanks"),
    ("c@acme.com", "Re: hello", "Do not contact me again.\nOn Mon, X wrote:\n> hi"),
    ("d@acme.com", "STOP", "Stop emailing me."),
]
AUTO = [
    ("e@acme.com", "Automatic reply: Quick question", "I am out of the office until Monday."),
    ("f@acme.com", "Out of office", "Thanks for your email. I'm on leave."),
    ("g@acme.com", "Re: hello", "Auto-reply: away from my desk until the 4th."),
]
OTHER = [
    ("h@acme.com", "Re: Quick question", "Sounds interesting, can you send more detail?"),
    ("i@acme.com", "Re: hello", "Who are you?"),
    (
        "j@acme.com",
        "Re: hi",
        "> unsubscribe link is in the footer of the newsletter\nThanks, call me",
    ),
]


@pytest.mark.parametrize(("sender", "subject", "body"), HARD)
def test_hard_bounces(sender: str, subject: str, body: str) -> None:
    assert classify(sender, subject, body).category is C.HARD_BOUNCE


@pytest.mark.parametrize(("sender", "subject", "body"), SOFT)
def test_soft_bounces(sender: str, subject: str, body: str) -> None:
    assert classify(sender, subject, body).category is C.SOFT_BOUNCE


@pytest.mark.parametrize(("sender", "subject", "body"), OPT_OUT)
def test_opt_outs(sender: str, subject: str, body: str) -> None:
    assert classify(sender, subject, body).category is C.UNSUBSCRIBE


@pytest.mark.parametrize(("sender", "subject", "body"), AUTO)
def test_auto_replies(sender: str, subject: str, body: str) -> None:
    assert classify(sender, subject, body).category is C.OUT_OF_OFFICE


@pytest.mark.parametrize(("sender", "subject", "body"), OTHER)
def test_everything_else_waits_for_a_person(sender: str, subject: str, body: str) -> None:
    assert classify(sender, subject, body).category is C.OTHER


def test_a_bounce_names_who_it_could_not_reach() -> None:
    found = classify(*HARD[0])
    assert found.failed_recipient == "jane.doe@acme.co.uk"
    assert classify(*HARD[1]).failed_recipient == "jane@acme.co.uk"
