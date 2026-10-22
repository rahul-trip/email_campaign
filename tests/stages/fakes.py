"""Fake providers shared by the stage tests: they answer from canned data and count calls."""

from __future__ import annotations

import json
from typing import Any, ClassVar

from outbound.providers.ports import (
    LlmResult,
    PageText,
    RegistryEntry,
    SearchHit,
)

GOOD_BODY = (
    "Acme's Leeds office opened last month, and from the outside it looks like the solar fleet "
    "is about to get a lot bigger. That usually shows up first in the forecasts. Once a fleet "
    "runs across more sites, a small miss at each one adds up to a real imbalance bill, and the "
    "people running dispatch end up second-guessing the numbers they are given.\n\n"
    "We work on exactly that. For a UK trader we cut day-ahead forecast error by about a "
    "quarter using the data they already held, and the models plug into existing dispatch tools "
    "in days, not months. Nothing there needs a new platform or a long procurement.\n\n"
    "I don't know how you handle forecasting today, so this may be off the mark. If it isn't, "
    "I would value twenty minutes to show you what we did and hear where it would not fit. "
    "Would one of the next two weeks work for a short call?"
)
GOOD_DRAFT = {"subject": "leeds solar forecasts", "body": GOOD_BODY, "based_on": ""}


class FakeLlm:
    """Answers by the role named in the system prompt; ``replies`` overrides a role's JSON."""

    name = "fake-llm"
    model = "fake-model"

    ROLES: ClassVar[dict[str, str]] = {
        "read a company's own web pages": "site",
        "answer a salesperson's research questions": "signals",
        "extract the people listed": "persona",
        "judge how well a company matches": "fit",
        "pick the news worth opening": "news",
        "You write the first email from one person": "actor",
        "You check a cold email before it goes": "critic",
    }

    def __init__(self, replies: dict[str, Any] | None = None) -> None:
        self.calls: list[str] = []
        self.users: dict[str, str] = {}
        self.replies: dict[str, Any] = {
            "site": {
                "sector": "grid forecasting software",
                "summary": "Acme builds grid forecasting software for utilities.",
                "products": ["Forecaster"],
                "news": ["Opened a Leeds office"],
                "hooks": ["Their Leeds office opening"],
            },
            "signals": {
                "answers": {"Do they trade power?": "Yes, via a trading desk."},
                "hiring": "Hiring two data scientists",
                "tech": ["Python"],
            },
            "persona": {
                "people": [
                    {"name": "Jane Doe", "title": "CTO", "linkedin_url": ""},
                    {"name": "Cher", "title": "Singer"},
                ]
            },
            "fit": {"score": 82, "reason": "Utility forecasting is exactly the target."},
            "news": {"company": [], "market": []},
            "actor": GOOD_DRAFT,
            "critic": {"grounded": True, "human": True, "problem": ""},
        }
        self.replies.update(replies or {})

    def complete(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LlmResult:
        role = next((r for needle, r in self.ROLES.items() if needle in system), "unknown")
        self.calls.append(role)
        self.users[role] = user
        reply = self.replies[role]
        text = reply if isinstance(reply, str) else json.dumps(reply)
        return LlmResult(text=text, provider=self.name, model=self.model)


class FakeSearch:
    name = "fake-search"

    def __init__(
        self,
        pages: dict[str, str] | None = None,
        hits: list[SearchHit] | None = None,
        news: list[SearchHit] | None = None,
        market_news: list[SearchHit] | None = None,
    ) -> None:
        self.pages = {} if pages is None else pages
        self.hits = hits or []
        self.news = news or []  # answers the search for the company's own news
        self.market_news = market_news or []  # answers the search for its market (has "OR")
        self.searches: list[str] = []  # general searches only
        self.news_searches: list[tuple[str, int | None]] = []  # (query, days)
        self.extracted: list[list[str]] = []

    def search(
        self, query: str, *, max_results: int = 5, topic: str = "general", days: int | None = None
    ) -> list[SearchHit]:
        if topic == "news":
            self.news_searches.append((query, days))
            return self.market_news if " OR " in query else self.news
        self.searches.append(query)
        return self.hits

    def extract(self, urls: list[str]) -> list[PageText]:
        self.extracted.append(urls)
        return [PageText(url=u, text=self.pages[u]) for u in urls if u in self.pages]


class FakeRegistry:
    name = "fake-registry"

    def __init__(self, entries: list[RegistryEntry] | None = None) -> None:
        self.entries = entries or []
        self.queries: list[str] = []

    def search(self, company_name: str, *, max_results: int = 5) -> list[RegistryEntry]:
        self.queries.append(company_name)
        return self.entries


TEAM_PAGE = (
    "Our leadership team. Jane Doe is our Chief Technology Officer and leads the engineering "
    "group in Leeds, with twenty years in energy software. Cher runs our front desk."
)
UK_FOOTER = "Acme Energy Ltd. Registered in England and Wales. Company number 01234567. LS1 4AP"
PAGES = {
    "https://acme.co.uk": "Acme builds grid forecasting software for utilities.",
    "https://acme.co.uk/team": TEAM_PAGE,
    "https://acme.co.uk/contact": UK_FOOTER,
}


class ScriptedLlm:
    """Replies in order per role (the last reply repeats), and records every prompt it was sent."""

    name = "scripted"
    model = "scripted-model"
    ROLES = (
        ("You write the first email from one person", "actor"),
        ("You check a cold email before it goes", "critic"),
    )

    def __init__(self, actor: list[Any], critic: list[Any] | None = None) -> None:
        self._script = {"actor": list(actor), "critic": list(critic or [])}
        self.calls: list[str] = []
        self.prompts: dict[str, list[str]] = {"actor": [], "critic": []}
        self.systems: dict[str, list[str]] = {"actor": [], "critic": []}

    def complete(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LlmResult:
        role = next(r for needle, r in self.ROLES if needle in system)
        self.calls.append(role)
        self.prompts[role].append(user)
        self.systems[role].append(system)
        queue = self._script[role]
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        text = reply if isinstance(reply, str) else json.dumps(reply)
        return LlmResult(text=text, provider=self.name, model=self.model)


class FakeMailbox:
    """An in-memory mailbox: drafts go in, and the test decides what appears in Sent."""

    address = "sam@quantra.example"

    def __init__(self) -> None:
        self.drafts: dict[str, Any] = {}
        self.appends = 0
        self.sent: list[Any] = []

    def append_draft(self, draft: Any) -> str:
        self.appends += 1
        self.drafts[draft.message_id] = draft
        return str(draft.message_id)

    def draft_exists(self, remote_draft_id: str) -> bool:
        return remote_draft_id in self.drafts

    def delete_draft(self, remote_draft_id: str) -> int:
        return int(self.drafts.pop(remote_draft_id, None) is not None)

    def list_sent(self, since: Any) -> list[Any]:
        return [m for m in self.sent if m.sent_at >= since]

    def list_inbox(self, since: Any) -> list[Any]:
        return []
