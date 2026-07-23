"""agent/providers/bundle.py — ProviderBundle + build_providers factory.

Dependency Injection: providers are built once here and injected into every
LangGraph node via closures in graph/build.py. Nodes never construct providers
themselves, which keeps them unit-testable with fakes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from agent.config.models import AgentConfig
from .contacts import get_contact_provider
from .contacts.base import ContactResolutionProvider
from .copywriter import get_copywriter
from .copywriter.base import CopywriterProvider
from .discovery import get_discovery_provider
from .discovery.base import CompanyDiscoveryProvider
from .email_finder import get_email_finder
from .email_finder.base import EmailFinderProvider
from .verifier import get_verifier
from .verifier.base import EmailVerifierProvider


@dataclass(frozen=True)
class ProviderBundle:
    """Immutable container of all five provider instances.

    Built once in main.py via build_providers() and passed to build_graph().
    """

    discovery: CompanyDiscoveryProvider
    contacts: ContactResolutionProvider
    email_finder: EmailFinderProvider
    verifier: EmailVerifierProvider
    copywriter: CopywriterProvider


def build_providers(config: AgentConfig) -> ProviderBundle:
    """Instantiate all providers from config + environment secrets.

    Reads API keys from os.environ (loaded by config/loader.py via dotenv).

    Args:
        config: The fully-loaded AgentConfig.

    Returns:
        A ProviderBundle ready for injection into the graph.
    """
    delay = config.per_call_delay_seconds
    pnames = config.providers

    # Each discovery provider reads its own key; only google_cse also needs cx.
    discovery_api_key = (
        os.getenv("GOOGLE_CSE_KEY", "") if pnames.discovery == "google_cse"
        else os.getenv("TAVILY_API_KEY", "")
    )
    discovery = get_discovery_provider(
        pnames.discovery,
        api_key=discovery_api_key,
        cx=os.getenv("GOOGLE_CSE_CX", ""),
        per_call_delay_seconds=delay,
    )

    # Each contact provider reads its own key; brightdata also needs a dataset_id.
    contacts_api_key = (
        os.getenv("PROXYCURL_API_KEY", "") if pnames.contacts == "proxycurl"
        else os.getenv("BRIGHTDATA_API_KEY", "")
    )
    contacts = get_contact_provider(
        pnames.contacts,
        api_key=contacts_api_key,
        dataset_id=os.getenv("BRIGHTDATA_LINKEDIN_DATASET_ID", ""),
        per_call_delay_seconds=delay,
    )

    email_finder = get_email_finder(
        pnames.email_finder,
        api_key=os.getenv("HUNTER_API_KEY", ""),
        per_call_delay_seconds=delay,
    )

    verifier = get_verifier(
        pnames.verifier,
        api_key=os.getenv("NEVERBOUNCE_API_KEY", ""),
        per_call_delay_seconds=delay,
    )

    copywriter = get_copywriter(
        pnames.copywriter,
        llm=config.llm,
        sender=config.sender,
        per_call_delay_seconds=delay,
    )

    return ProviderBundle(
        discovery=discovery,
        contacts=contacts,
        email_finder=email_finder,
        verifier=verifier,
        copywriter=copywriter,
    )
