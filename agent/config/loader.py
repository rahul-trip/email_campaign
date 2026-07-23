"""agent/config/loader.py — parses config.yaml + .env into an AgentConfig.

Usage:
    from agent.config.loader import load_config
    cfg = load_config()                   # uses agent/config.yaml by default
    cfg = load_config("path/to/cfg.yaml") # explicit path
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

from .models import AgentConfig, ConfigError, LlmConfig, ProviderNames, SenderProfile

# Default config path relative to *this file's* directory (agent/config/)
_DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


def load_config(path: str | Path | None = None) -> AgentConfig:
    """Parse YAML + .env and return a fully-resolved, validated AgentConfig.

    Secrets (API keys) are read from os.environ; they must be present in
    .env (root or agent/.env) or the calling environment.

    Raises:
        ConfigError: if any required YAML key is missing or xlsx_path is bad.
    """
    # --- load secrets from .env (root first, then agent/.env, later wins) ----
    root = Path(__file__).parent.parent.parent
    load_dotenv(root / ".env", override=False)
    load_dotenv(Path(__file__).parent.parent / ".env", override=True)

    # --- read YAML -----------------------------------------------------------
    config_path = Path(path) if path else _DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise ConfigError(
            f"Config file not found: {config_path}. "
            "Copy config.example.yaml to config.yaml and edit it."
        )

    with config_path.open() as fh:
        raw = yaml.safe_load(fh) or {}

    # --- validate and extract ------------------------------------------------
    missing: list[str] = []

    def _get(d: dict, *keys: str, default=None, required: bool = True):
        val = d
        for k in keys:
            if not isinstance(val, dict) or k not in val:
                if required:
                    missing.append(".".join(keys))
                return default
            val = val[k]
        return val

    campaign = raw.get("campaign", {})
    limits = raw.get("limits", {})
    providers_raw = raw.get("providers", {})
    verification = raw.get("verification", {})
    output = raw.get("output", {})

    keywords = _get(campaign, "keywords", required=True) or []
    location = _get(campaign, "location", required=True) or ""
    target_titles = _get(campaign, "target_titles", required=False, default=[]) or []

    max_companies = _get(limits, "max_companies", required=False, default=10)
    max_leads = _get(limits, "max_leads", required=False, default=10)
    per_call_delay = _get(limits, "per_call_delay_seconds", required=False, default=1.0)

    provider_names = ProviderNames(
        discovery=_get(providers_raw, "discovery", required=True) or "tavily",
        contacts=_get(providers_raw, "contacts", required=True) or "brightdata",
        email_finder=_get(providers_raw, "email_finder", required=True) or "hunter",
        verifier=_get(providers_raw, "verifier", required=True) or "neverbounce",
        copywriter=_get(providers_raw, "copywriter", required=False, default="template") or "template",
    )

    keep_statuses = _get(verification, "keep_statuses", required=False, default=["valid", "catchall", "unknown"])
    mark_risky = _get(verification, "mark_risky_statuses", required=False, default=["catchall", "unknown"])

    xlsx_rel = _get(output, "xlsx_path", required=True) or ""
    run_drafts_after = _get(output, "run_drafts_after", required=False, default=True)
    signature_name = _get(output, "signature_name", required=False, default="[Your Name]")
    signature_title = _get(output, "signature_title", required=False, default="CPO & Founder")

    # --- sender profile --------------------------------------------------
    sender_raw = raw.get("sender", {})
    company_name = _get(sender_raw, "company_name", required=True) or ""

    profile_rel = _get(sender_raw, "profile_path", required=False, default="sender_profile.md")
    profile_file = config_path.parent / profile_rel
    narrative = profile_file.read_text(encoding="utf-8") if profile_file.exists() else ""

    sender = SenderProfile(
        company_name=str(company_name),
        domain=str(_get(sender_raw, "domain", required=False, default="")),
        industry=str(_get(sender_raw, "industry", required=False, default="")),
        mission=str(_get(sender_raw, "mission", required=False, default="")),
        value_propositions=tuple(_get(sender_raw, "value_propositions", required=False, default=[]) or []),
        technologies=tuple(_get(sender_raw, "technologies", required=False, default=[]) or []),
        target_verticals=tuple(_get(sender_raw, "target_verticals", required=False, default=[]) or []),
        case_studies=tuple(_get(sender_raw, "case_studies", required=False, default=[]) or []),
        geographic_focus=str(_get(sender_raw, "geographic_focus", required=False, default="")),
        narrative=narrative,
    )

    # --- llm block (only matters when providers.copywriter == "llm") -----
    llm_raw = raw.get("llm", {})
    llm = LlmConfig(
        provider=str(llm_raw.get("provider", "anthropic")),
        model=str(llm_raw.get("model", "claude-sonnet-5")),
        base_url=str(llm_raw.get("base_url", "")),
        key_env=str(llm_raw.get("key_env", "")),
        temperature=float(llm_raw.get("temperature", 0.7)),
        max_tokens=int(llm_raw.get("max_tokens", 1200)),
    )

    if missing:
        raise ConfigError(f"Config file is missing required key(s): {missing}")

    # resolve xlsx_path relative to the config file's directory
    xlsx_path = str((config_path.parent / xlsx_rel).resolve())

    if not keywords:
        raise ConfigError("campaign.keywords must be a non-empty list of strings.")

    if provider_names.copywriter not in ("template", "llm"):
        raise ConfigError(
            f"providers.copywriter must be 'template' or 'llm', got {provider_names.copywriter!r}"
        )
    if provider_names.copywriter == "llm" and not sender.narrative:
        raise ConfigError(
            f"providers.copywriter is 'llm' but {profile_file} is missing or empty. "
            "Create sender_profile.md next to config.yaml (see sender_profile.example.md)."
        )

    return AgentConfig(
        keywords=list(keywords),
        location=str(location),
        target_titles=list(target_titles),
        max_companies=int(max_companies),
        max_leads=int(max_leads),
        per_call_delay_seconds=float(per_call_delay),
        providers=provider_names,
        keep_statuses=list(keep_statuses),
        mark_risky_statuses=list(mark_risky),
        xlsx_path=xlsx_path,
        run_drafts_after=bool(run_drafts_after),
        signature_name=str(signature_name),
        signature_title=str(signature_title),
        sender=sender,
        llm=llm,
    )
