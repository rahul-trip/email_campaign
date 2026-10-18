"""Builds adapters by name from settings, so the chain is a config choice, not code.

``configured_*`` returns only the adapters whose credentials are present; ``build_*`` raises
if a requested one is not configured. Both accept a shared ``httpx.Client`` so a script can
record every vendor response.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import httpx
from pydantic import SecretStr

from outbound.config import Settings
from outbound.providers.adapters.companies_house import CompaniesHouse
from outbound.providers.adapters.enrichley import EnrichleyResolver
from outbound.providers.adapters.hunter import HunterFinder, HunterVerifier
from outbound.providers.adapters.imap_mailbox import ImapMailbox
from outbound.providers.adapters.llm import OpenAiCompatibleLlm
from outbound.providers.adapters.myemailverifier import MyEmailVerifierVerifier
from outbound.providers.adapters.orbisearch import OrbiSearchVerifier
from outbound.providers.adapters.scrubby import ScrubbyResolver
from outbound.providers.adapters.tavily import TavilySearch
from outbound.providers.adapters.zerobounce import ZeroBounceFinder, ZeroBounceVerifier
from outbound.providers.errors import ProviderAuthError
from outbound.providers.ports import (
    CatchAllResolver,
    CompanyRegistry,
    EmailFinder,
    EmailVerifier,
    LlmClient,
    Mailbox,
    SearchProvider,
)


def _key(secret: SecretStr) -> str:
    return secret.get_secret_value()


@dataclass(frozen=True)
class _Entry[T]:
    build: Callable[[Settings, httpx.Client | None], T]
    is_configured: Callable[[Settings], bool]


_FINDERS: dict[str, _Entry[EmailFinder]] = {
    "hunter": _Entry(
        lambda s, c: HunterFinder(_key(s.hunter_api_key), client=c),
        lambda s: bool(_key(s.hunter_api_key)),
    ),
    "zerobounce": _Entry(
        lambda s, c: ZeroBounceFinder(_key(s.zerobounce_api_key), client=c),
        lambda s: bool(_key(s.zerobounce_api_key)),
    ),
}

_VERIFIERS: dict[str, _Entry[EmailVerifier]] = {
    "hunter": _Entry(
        lambda s, c: HunterVerifier(_key(s.hunter_api_key), client=c),
        lambda s: bool(_key(s.hunter_api_key)),
    ),
    "zerobounce": _Entry(
        lambda s, c: ZeroBounceVerifier(_key(s.zerobounce_api_key), client=c),
        lambda s: bool(_key(s.zerobounce_api_key)),
    ),
    "orbisearch": _Entry(
        lambda s, c: OrbiSearchVerifier(_key(s.orbisearch_api_key), client=c),
        lambda s: bool(_key(s.orbisearch_api_key)),
    ),
    "myemailverifier": _Entry(
        lambda s, c: MyEmailVerifierVerifier(_key(s.myemailverifier_api_key), client=c),
        lambda s: bool(_key(s.myemailverifier_api_key)),
    ),
}

_RESOLVERS: dict[str, _Entry[CatchAllResolver]] = {
    "scrubby": _Entry(
        lambda s, c: ScrubbyResolver(_key(s.scrubby_api_key), s.scrubby_base_url, client=c),
        lambda s: bool(_key(s.scrubby_api_key) and s.scrubby_base_url),
    ),
    "enrichley": _Entry(
        lambda s, c: EnrichleyResolver(_key(s.enrichley_api_key), client=c),
        lambda s: bool(_key(s.enrichley_api_key)),
    ),
}


def _configured[T](
    table: dict[str, _Entry[T]], settings: Settings, client: httpx.Client | None
) -> dict[str, T]:
    return {
        name: entry.build(settings, client)
        for name, entry in table.items()
        if entry.is_configured(settings)
    }


def _build[T](
    table: dict[str, _Entry[T]], names: list[str], settings: Settings, client: httpx.Client | None
) -> list[T]:
    built: list[T] = []
    for name in names:
        entry = table.get(name)
        if entry is None:
            raise ProviderAuthError(name, f"unknown provider; choose from {sorted(table)}")
        if not entry.is_configured(settings):
            raise ProviderAuthError(
                name, "not configured: its API key is missing in the environment"
            )
        built.append(entry.build(settings, client))
    return built


def configured_finders(
    settings: Settings, client: httpx.Client | None = None
) -> dict[str, EmailFinder]:
    return _configured(_FINDERS, settings, client)


def configured_verifiers(
    settings: Settings, client: httpx.Client | None = None
) -> dict[str, EmailVerifier]:
    return _configured(_VERIFIERS, settings, client)


def configured_resolvers(
    settings: Settings, client: httpx.Client | None = None
) -> dict[str, CatchAllResolver]:
    return _configured(_RESOLVERS, settings, client)


def build_finder_chain(settings: Settings, client: httpx.Client | None = None) -> list[EmailFinder]:
    return _build(_FINDERS, settings.finder_chain, settings, client)


def build_verifier(settings: Settings, client: httpx.Client | None = None) -> EmailVerifier:
    return _build(_VERIFIERS, [settings.verifier], settings, client)[0]


def build_resolver(settings: Settings, client: httpx.Client | None = None) -> CatchAllResolver:
    return _build(_RESOLVERS, [settings.catch_all_resolver], settings, client)[0]


def build_llm(settings: Settings, client: httpx.Client | None = None) -> LlmClient:
    """The configured chat model. The key comes from the vendor's own variable, else LLM_API_KEY."""
    own = {
        "anthropic": settings.anthropic_api_key,
        "openai": settings.openai_api_key,
        "gemini": settings.gemini_api_key,
        "github_copilot": settings.copilot_api_key,
    }.get(settings.llm_provider, settings.llm_api_key)
    return OpenAiCompatibleLlm(
        settings.llm_provider,
        settings.llm_model,
        _key(own) or _key(settings.llm_api_key),
        base_url=settings.llm_base_url,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        client=client,
    )


def build_company_registry(
    settings: Settings, client: httpx.Client | None = None
) -> CompanyRegistry | None:
    """Companies House, or ``None`` with no key (a UK lead then stays "legal entity unknown")."""
    key = _key(settings.companies_house_api_key)
    return CompaniesHouse(key, client=client) if key else None


def build_mailbox(settings: Settings) -> Mailbox:
    return ImapMailbox(
        host=settings.imap_host,
        address=settings.email_address,
        password=_key(settings.email_password),
        port=settings.imap_port,
        use_ssl=settings.imap_use_ssl,
        from_name=settings.from_name,
        drafts_folder=settings.drafts_folder,
        sent_folder=settings.sent_folder,
        inbox_folder=settings.inbox_folder,
    )


def build_search(settings: Settings, client: httpx.Client | None = None) -> SearchProvider:
    return TavilySearch(_key(settings.tavily_api_key), client=client)
