"""Builds adapters by name from settings, so the chain is a config choice, not code.

``configured_*`` returns only the adapters whose credentials are present; ``build_*`` raises
if a requested one is not configured. Both accept a shared ``httpx.Client`` so a script can
record every vendor response.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

import httpx
from pydantic import SecretStr

from outbound.config import Settings
from outbound.domain.enums import MailboxGateway
from outbound.domain.errors import ConfigurationError
from outbound.domain.vendors import BY_CODE
from outbound.providers import oauth
from outbound.providers.adapters.anymailfinder import AnymailFinder
from outbound.providers.adapters.companies_house import CompaniesHouse
from outbound.providers.adapters.enrichley import EnrichleyResolver
from outbound.providers.adapters.exa import ExaSearch
from outbound.providers.adapters.generect import GenerectFinder
from outbound.providers.adapters.hunter import HunterFinder, HunterVerifier
from outbound.providers.adapters.icypeas import IcypeasFinder
from outbound.providers.adapters.llm import OpenAiCompatibleLlm
from outbound.providers.adapters.myemailverifier import MyEmailVerifierVerifier
from outbound.providers.adapters.orbisearch import OrbiSearchResolver, OrbiSearchVerifier
from outbound.providers.adapters.prospeo import ProspeoFinder
from outbound.providers.adapters.scrubby import ScrubbyResolver
from outbound.providers.adapters.tavily import TavilySearch
from outbound.providers.adapters.yc_directory import YcDirectory
from outbound.providers.adapters.zerobounce import ZeroBounceFinder, ZeroBounceVerifier
from outbound.providers.errors import ProviderAuthError
from outbound.providers.keypool import KeyPool, ResolverKeyPool, key_label
from outbound.providers.oauth import OAuthApp
from outbound.providers.ports import (
    CatchAllResolver,
    CompanyRegistry,
    EmailFinder,
    EmailVerifier,
    LeadSource,
    LlmClient,
    SearchProvider,
    TransactionalEmail,
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
    "anymailfinder": _Entry(
        lambda s, c: AnymailFinder(_key(s.anymailfinder_api_key), client=c),
        lambda s: bool(_key(s.anymailfinder_api_key)),
    ),
    "prospeo": _Entry(
        lambda s, c: ProspeoFinder(_key(s.prospeo_api_key), client=c),
        lambda s: bool(_key(s.prospeo_api_key)),
    ),
    "icypeas": _Entry(
        lambda s, c: IcypeasFinder(_key(s.icypeas_api_key), client=c),
        lambda s: bool(_key(s.icypeas_api_key)),
    ),
    "generect": _Entry(
        lambda s, c: GenerectFinder(_key(s.generect_api_key), client=c),
        lambda s: bool(_key(s.generect_api_key)),
    ),
}

_VERIFIERS: dict[str, _Entry[EmailVerifier]] = {
    # Order matters: backups are tried in it, the vendors that only verify before the finders.
    "orbisearch": _Entry(
        lambda s, c: OrbiSearchVerifier(_key(s.orbisearch_api_key), client=c),
        lambda s: bool(_key(s.orbisearch_api_key)),
    ),
    "myemailverifier": _Entry(
        lambda s, c: MyEmailVerifierVerifier(_key(s.myemailverifier_api_key), client=c),
        lambda s: bool(_key(s.myemailverifier_api_key)),
    ),
    "hunter": _Entry(
        lambda s, c: HunterVerifier(_key(s.hunter_api_key), client=c),
        lambda s: bool(_key(s.hunter_api_key)),
    ),
    "zerobounce": _Entry(
        lambda s, c: ZeroBounceVerifier(_key(s.zerobounce_api_key), client=c),
        lambda s: bool(_key(s.zerobounce_api_key)),
    ),
}

_RESOLVERS: dict[str, _Entry[CatchAllResolver]] = {
    "scrubby": _Entry(
        lambda s, c: ScrubbyResolver(_key(s.scrubby_api_key), s.scrubby_base_url, client=c),
        lambda s: bool(_key(s.scrubby_api_key)),
    ),
    "enrichley": _Entry(
        lambda s, c: EnrichleyResolver(_key(s.enrichley_api_key), client=c),
        lambda s: bool(_key(s.enrichley_api_key)),
    ),
    "orbisearch": _Entry(
        lambda s, c: OrbiSearchResolver(_key(s.orbisearch_api_key), client=c),
        lambda s: bool(_key(s.orbisearch_api_key)),
    ),
}


def _pooled[T](
    code: str, build_one: Callable[[Settings], T], settings: Settings, *, resolver: bool = False
) -> T:
    """The vendor's adapter, or, when it has several keys, one per key behind a ``KeyPool``
    that uses a random one for each call and skips a refused one."""
    keys = settings.vendor_key_pools.get(code, [])
    if len(keys) < 2:
        return build_one(settings)
    setting = BY_CODE[code].setting
    members = [build_one(settings.model_copy(update={setting: key})) for key in keys]
    if resolver:
        labels = [key_label(key.get_secret_value()) for key in keys]
        return cast(T, ResolverKeyPool(members, labels=labels))
    return cast(T, KeyPool(members))


def _from_table[T](
    table: dict[str, _Entry[T]],
    name: str,
    entry: _Entry[T],
    settings: Settings,
    client: httpx.Client | None,
) -> T:
    def one(s: Settings) -> T:
        return entry.build(s, client)

    return _pooled(name, one, settings, resolver=table is _RESOLVERS)


def _configured[T](
    table: dict[str, _Entry[T]], settings: Settings, client: httpx.Client | None
) -> dict[str, T]:
    return {
        name: _from_table(table, name, entry, settings, client)
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
        built.append(_from_table(table, name, entry, settings, client))
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


def build_finder_named(
    name: str, settings: Settings, client: httpx.Client | None = None
) -> EmailFinder:
    """One particular finder, whatever the chain is set to (a key test uses it)."""
    return _build(_FINDERS, [name], settings, client)[0]


def build_verifier(settings: Settings, client: httpx.Client | None = None) -> EmailVerifier:
    return _build(_VERIFIERS, [settings.verifier], settings, client)[0]


def build_verifier_named(
    name: str, settings: Settings, client: httpx.Client | None = None
) -> EmailVerifier:
    """One particular verifier, whatever the chain is set to (a key test uses it)."""
    return _build(_VERIFIERS, [name], settings, client)[0]


def build_resolver(settings: Settings, client: httpx.Client | None = None) -> CatchAllResolver:
    return _build(_RESOLVERS, [settings.catch_all_resolver], settings, client)[0]


def build_llm(
    settings: Settings, client: httpx.Client | None = None, *, model: str = ""
) -> LlmClient:
    """The configured chat model, or ``model`` on the same provider (the writer's, for example).

    The key comes from the vendor's own variable, else LLM_API_KEY (the one the console's
    several keys replace)."""
    return _pooled("llm", lambda s: _llm(s, client, model), settings)


def _llm(settings: Settings, client: httpx.Client | None, model: str) -> LlmClient:
    own = {
        "anthropic": settings.anthropic_api_key,
        "openai": settings.openai_api_key,
        "gemini": settings.gemini_api_key,
        "github_copilot": settings.copilot_api_key,
    }.get(settings.llm_provider, settings.llm_api_key)
    return OpenAiCompatibleLlm(
        settings.llm_provider,
        model or settings.llm_model,
        _key(own) or _key(settings.llm_api_key),
        base_url=settings.llm_base_url,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        reasoning_effort=settings.llm_reasoning_effort,
        client=client,
    )


def build_company_registry(
    settings: Settings, client: httpx.Client | None = None
) -> CompanyRegistry | None:
    """Companies House, or ``None`` with no key (a UK lead then stays "legal entity unknown")."""
    if not _key(settings.companies_house_api_key):
        return None
    return _pooled(
        "companies_house",
        lambda s: CompaniesHouse(_key(s.companies_house_api_key), client=client),
        settings,
    )


def build_company_sources(
    settings: Settings, client: httpx.Client | None = None
) -> list[LeadSource]:
    """Where discovery looks besides web search: the Y Combinator directory (no key), then
    the UK register and Exa when their keys are set."""
    sources: list[LeadSource] = [YcDirectory(client=client)]
    if _key(settings.companies_house_api_key):
        sources.append(
            _pooled(
                "companies_house",
                lambda s: CompaniesHouse(_key(s.companies_house_api_key), client=client),
                settings,
            )
        )
    if _key(settings.exa_api_key):
        sources.append(
            _pooled("exa", lambda s: ExaSearch(_key(s.exa_api_key), client=client), settings)
        )
    return sources


def build_oauth_apps(settings: Settings) -> dict[MailboxGateway, OAuthApp]:
    """The sign-in apps customers connect Microsoft 365 and Google mailboxes through. Only the
    ones set up on this server are offered."""
    apps = {
        MailboxGateway.GRAPH: oauth.microsoft(
            settings.microsoft_client_id, _key(settings.microsoft_client_secret)
        ),
        MailboxGateway.GMAIL: oauth.google(
            settings.google_client_id, _key(settings.google_client_secret)
        ),
    }
    return {gateway: app for gateway, app in apps.items() if app.configured}


def build_search(settings: Settings, client: httpx.Client | None = None) -> SearchProvider:
    return _pooled(
        "tavily", lambda s: TavilySearch(_key(s.tavily_api_key), client=client), settings
    )


def build_transactional_email(settings: Settings) -> TransactionalEmail:
    """SMTP when it is set up; otherwise the log (refused in production)."""
    from outbound.providers.adapters.transactional_email import LogEmail, SmtpEmail

    if settings.smtp_host:
        return SmtpEmail(
            settings.smtp_host,
            settings.smtp_port,
            settings.smtp_username,
            settings.smtp_password.get_secret_value(),
            settings.email_from,
        )
    if settings.environment == "production":
        raise ConfigurationError(
            "SMTP_HOST is not set, so invitations and password resets could not be sent. "
            "Set SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD and EMAIL_FROM."
        )
    return LogEmail()
