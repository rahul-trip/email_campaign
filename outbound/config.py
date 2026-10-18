"""Settings read from the environment (and a root ``.env``); secrets never live in code.

The provider chain below is PROVISIONAL until the Phase 0 bake-off has run. Change it here
(or with ``FINDER_CHAIN`` and friends in ``.env``) once the bake-off report picks a winner.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    # ``agent/.env`` is read as a fallback so the keys already there (Hunter, Tavily) work
    # without copying secrets. Drop it when the legacy ``agent/`` package is deleted in Phase 2.
    model_config = SettingsConfigDict(
        env_file=(".env", "agent/.env"), env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "sqlite:///outbound.db"

    # --- provider keys (blank means "not configured") ---
    hunter_api_key: SecretStr = SecretStr("")
    zerobounce_api_key: SecretStr = SecretStr("")
    orbisearch_api_key: SecretStr = SecretStr("")
    myemailverifier_api_key: SecretStr = SecretStr("")
    enrichley_api_key: SecretStr = SecretStr("")
    scrubby_api_key: SecretStr = SecretStr("")
    scrubby_base_url: str = ""  # the public docs do not state it; copy it from your Scrubby account
    tavily_api_key: SecretStr = SecretStr("")
    companies_house_api_key: SecretStr = SecretStr("")  # free key from Companies House

    # --- mailbox (IMAP). The names match the legacy agent/.env so existing values keep working ---
    imap_host: str = ""
    imap_port: int = 993
    imap_use_ssl: bool = True
    email_address: str = ""
    email_password: SecretStr = SecretStr("")
    from_name: str = ""
    drafts_folder: str = "INBOX.Drafts"
    sent_folder: str = "INBOX.Sent"
    inbox_folder: str = "INBOX"
    imap_timeout_seconds: float = 30.0  # a hung mail server must not freeze a run

    # --- language model: any OpenAI-compatible endpoint (see providers/adapters/llm.py) ---
    # anthropic, openai, gemini, ollama, github_copilot or openai_compatible
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-5-5"
    llm_base_url: str = ""  # only for openai_compatible (Groq, Together, ...) or a proxy
    llm_temperature: float = 0.7
    llm_max_tokens: int = 4_000  # reasoning models need room to think before answering
    llm_api_key: SecretStr = SecretStr("")  # used by openai_compatible, or as a fallback
    anthropic_api_key: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")
    gemini_api_key: SecretStr = SecretStr("")
    copilot_api_key: SecretStr = SecretStr("")

    # --- spend: override the built-in prices and set monthly caps (micro-USD; 1,000,000 = $1) ---
    provider_prices: dict[str, int | None] = {}  # {"hunter:find": 24500}
    llm_prices: dict[str, tuple[int, int]] = {}  # {"model": [input, output] per million tokens}
    monthly_caps_micro_usd: dict[str, int] = {}  # {"zerobounce": 20000000}

    # --- web app and API ---
    workspace_name: str = "default"
    operator_password_hash: str = ""  # an Argon2 hash: `uv run outbound auth hash-password`
    session_secret: SecretStr = SecretStr("")  # signs the session cookie; any long random string
    session_hours: int = 12
    intake_webhook_secret: SecretStr = SecretStr("")  # blank disables the webhook
    cookie_secure: bool = False  # set true when served over https
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    # --- email waterfall (provisional until the bake-off) ---
    # Finders are tried in this order. OrbiSearch is verify-only, so it cannot be a finder.
    finder_chain: Annotated[list[str], NoDecode] = ["hunter", "zerobounce"]
    verifier: str = "myemailverifier"
    catch_all_resolver: str = "scrubby"

    @field_validator("finder_chain", mode="before")
    @classmethod
    def _split_chain(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value
