"""agent/config/models.py — frozen config dataclasses.

Strategy: AgentConfig is the single source of truth for all runtime settings.
It is built once in loader.py and injected everywhere; nothing reads YAML or
os.environ after that point.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderNames:
    """Which concrete adapter to use for each capability (from config.yaml)."""

    discovery: str
    contacts: str
    email_finder: str
    verifier: str
    copywriter: str


@dataclass(frozen=True)
class SenderProfile:
    """Who is sending the emails.

    Facts (company_name..geographic_focus) come from config.yaml's sender:
    block. narrative comes verbatim from sender_profile.md and is never
    parsed — it's passed as-is to the LLM copywriter as free-form context.
    """

    company_name: str
    domain: str = ""
    industry: str = ""
    mission: str = ""
    value_propositions: tuple[str, ...] = ()
    technologies: tuple[str, ...] = ()
    target_verticals: tuple[str, ...] = ()
    case_studies: tuple[str, ...] = ()
    geographic_focus: str = ""
    narrative: str = ""


@dataclass(frozen=True)
class LlmConfig:
    """One flat LLM block, used only when providers.copywriter == 'llm'.

    provider selects a preset (base_url + auth env var) from
    providers/copywriter/llm_copywriter.py's _PROVIDER_PRESETS. base_url/
    key_env override the preset when set (required for "openai_compatible").
    """

    provider: str = "anthropic"
    model: str = "claude-sonnet-5"
    base_url: str = ""
    key_env: str = ""
    temperature: float = 0.7
    max_tokens: int = 1200


@dataclass(frozen=True)
class AgentConfig:
    """Immutable runtime configuration — never mutated after creation."""

    # Campaign targeting
    keywords: list[str]
    location: str
    target_titles: list[str]

    # Run limits (cost control)
    max_companies: int
    max_leads: int
    per_call_delay_seconds: float

    # Which adapters to use
    providers: ProviderNames

    # Verification policy (from spec Module B)
    keep_statuses: list[str]
    mark_risky_statuses: list[str]

    # Output
    xlsx_path: str          # absolute path resolved by loader
    run_drafts_after: bool
    signature_name: str
    signature_title: str

    # Sender identity + LLM copywriter settings
    sender: SenderProfile
    llm: LlmConfig


class ConfigError(ValueError):
    """Raised by loader.py when required config keys are absent or invalid."""
