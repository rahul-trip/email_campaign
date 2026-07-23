"""agent/providers/discovery/_common.py — Shared helpers for discovery adapters.

Both google_cse.py and tavily.py return generic web-search results that need
the same cleanup: skip obviously-non-company domains, and extract a root
domain from a result URL for deduplication. Factored out so adding a third
search-based discovery adapter doesn't mean re-copying this logic.
"""

from __future__ import annotations

from urllib.parse import urlparse

# Domains that are clearly not companies — skip results from these.
DOMAIN_BLOCKLIST = frozenset({
    "linkedin.com", "facebook.com", "twitter.com", "instagram.com",
    "wikipedia.org", "youtube.com", "bloomberg.com", "crunchbase.com",
    "indeed.com", "glassdoor.com", "reddit.com", "github.com",
    "amazon.com", "google.com", "bing.com",
})


def extract_domain(url: str) -> str:
    """Return the root domain (no www.) from a URL, or empty string."""
    try:
        host = urlparse(url).hostname or ""
        return host.lower().removeprefix("www.")
    except Exception:
        return ""
