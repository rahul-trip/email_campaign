"""Turning whatever an operator typed into a registrable root domain.

Uses the public-suffix snapshot bundled with ``tldextract`` and never fetches the list, so
results are deterministic and tests stay offline.
"""

from __future__ import annotations

import re

import tldextract

_EXTRACT = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)

# Addresses and sites that are never a target company.
FREE_MAIL_DOMAINS = frozenset(
    {
        "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "msn.com",
        "yahoo.com", "ymail.com", "icloud.com", "me.com", "aol.com", "proton.me",
        "protonmail.com", "gmx.com", "gmx.de", "web.de", "mail.com", "zoho.com", "yandex.com",
    }
)  # fmt: skip
PLATFORM_DOMAINS = frozenset(
    {
        "linkedin.com", "facebook.com", "twitter.com", "x.com", "instagram.com", "youtube.com",
        "github.com", "wikipedia.org", "crunchbase.com", "medium.com", "reddit.com",
        "glassdoor.com", "indeed.com", "bloomberg.com", "reuters.com", "forbes.com",
        "amazon.com", "google.com", "bing.com",
    }
)  # fmt: skip

_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)


def registrable_domain(value: str) -> str | None:
    """``https://uk.Example.co.uk/about?x=1`` becomes ``example.co.uk``; junk becomes None.

    Accepts a URL, a bare host, or an email address.
    """
    text = value.strip().lower()
    if not text:
        return None
    if "@" in text and not _SCHEME.match(text):
        text = text.rsplit("@", 1)[1]
    text = _SCHEME.sub("", text)
    host = re.split(r"[/?#]", text, maxsplit=1)[0].split(":")[0]
    parts = _EXTRACT(host)
    if not parts.domain or not parts.suffix:
        return None
    return f"{parts.domain}.{parts.suffix}"


def is_free_mail(domain: str) -> bool:
    return domain in FREE_MAIL_DOMAINS


def is_platform(domain: str) -> bool:
    return domain in PLATFORM_DOMAINS
