"""Exa: neural web search limited to company sites, and companies like an example customer.

Docs: https://docs.exa.ai/reference/search and https://docs.exa.ai/reference/find-similar-links
The key goes in the ``x-api-key`` header. ``/search`` with ``category: company`` returns company
home pages for a description of the companies wanted; ``/findSimilar`` returns pages like a
given one, which finds lookalikes of an example customer. A short extract of each page's text
comes back with it, for screening. Paid per request.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from outbound.domain.discovery import EXA
from outbound.domain.domains import registrable_domain
from outbound.providers.http import HttpClient, require_api_key
from outbound.providers.ports import CompanyMention, SourceQuery

BASE_URL = "https://api.exa.ai"
MAX_RESULTS = 25  # one request's price covers up to 25 results
MAX_SEEDS = 2  # lookalike requests per search
TEXT_CHARS = 600
# "Name | tagline", "Name - tagline", "Name: tagline", with an en or em dash too.
_TITLE_SPLIT = re.compile(r"\s+[|\-\u2013\u2014\u00b7]\s+|:\s+")
_DOMAIN = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")


class ExaSearch:
    name = EXA

    def __init__(self, api_key: str, *, client: httpx.Client | None = None) -> None:
        key = require_api_key(self.name, api_key)
        self._http = HttpClient(self.name, BASE_URL, headers={"x-api-key": key}, client=client)

    def find(self, query: SourceQuery, *, limit: int) -> list[CompanyMention]:
        """Companies the query describes, then lookalikes of its example customers' websites."""
        size = max(1, min(limit, MAX_RESULTS))
        contents = {"text": {"maxCharacters": TEXT_CHARS}}
        found: dict[str, CompanyMention] = {}
        text = query.text.strip() or _described(query)
        if text:
            payload = self._http.post_object(
                "/search",
                {"query": text, "type": "auto", "category": "company", "numResults": size,
                 "contents": contents},
            )  # fmt: skip
            _collect(found, payload, "")
        # Example customers given as websites; a bare name cannot be looked alike.
        seeds = [s.lower() for s in query.seed_domains if _DOMAIN.match(s.lower())]
        for seed in seeds[:MAX_SEEDS]:
            payload = self._http.post_object(
                "/findSimilar",
                {"url": f"https://{seed}", "numResults": size, "excludeSourceDomain": True,
                 "category": "company", "contents": contents},
            )  # fmt: skip
            _collect(found, payload, seed)
        return list(found.values())


def _described(query: SourceQuery) -> str:
    what = " ".join([*query.keywords[:2], *(query.segments[:1] or ("companies",))])
    where = f" in {', '.join(query.regions[:3])}" if query.regions else ""
    return f"{what}{where}" if query.keywords or query.segments else ""


def _collect(found: dict[str, CompanyMention], payload: dict[str, Any], seed: str) -> None:
    for item in payload.get("results") or []:
        url = str(item.get("url") or "")
        domain = registrable_domain(url) if url else None
        if not domain or domain in found:
            continue
        title = " ".join(str(item.get("title") or "").split())
        name = _TITLE_SPLIT.split(title, maxsplit=1)[0].strip() or domain
        text = " ".join(str(item.get("text") or "").split())
        evidence = f"Exa, like {seed}: {text[:300]}" if seed else f"Exa: {text[:300]}"
        found[domain] = CompanyMention(
            name=name,
            domain=domain,
            description=text,
            source=EXA,
            source_url=url,
            evidence=evidence,
        )
