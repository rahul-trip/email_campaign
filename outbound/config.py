"""Settings read from the environment (and a root ``.env``); secrets never live in code.

The provider chain below is PROVISIONAL until the Phase 0 bake-off has run. Change it here
(or with ``FINDER_CHAIN`` and friends in ``.env``) once the bake-off report picks a winner.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    # ``agent/.env`` is read as a fallback so the keys already there (Hunter, Tavily) work
    # without copying secrets. Drop it when the legacy ``agent/`` package is deleted in Phase 2.
    model_config = SettingsConfigDict(
        env_file=(".env", "agent/.env"), env_file_encoding="utf-8", extra="ignore"
    )

    # --- database: switch with DATABASE_BACKEND; both settings can sit in .env side by side ---
    database_backend: Literal["sqlite", "postgres"] = "sqlite"
    sqlite_path: str = "outbound.db"
    postgres_url: str = ""  # e.g. Supabase's session pooler; postgresql:// is fine
    # The role that reads across workspaces (the scheduler, the admin console). Blank: the same
    # connection as POSTGRES_URL, which is right for SQLite and for development.
    postgres_platform_url: str = ""
    # The tables' owner, for `db upgrade` and `seed` only (Phase 6a). Blank: POSTGRES_URL. In
    # production prefer a separate Doppler config for the migrate container (docs/DEPLOY.md).
    postgres_migrate_url: str = ""
    # Set it to bypass the switch (the tests and --database-url do). Otherwise it is worked out
    # from the three settings above.
    database_url: str = ""
    platform_database_url: str = ""  # worked out like database_url; see postgres_platform_url
    migrate_database_url: str = ""  # worked out like database_url; see postgres_migrate_url
    # Connections each process keeps open to Postgres. Supabase's session pooler allows few
    # clients in all (15 on the small plans), and the api, worker and CLI each have a pool.
    database_pool_size: int = 5

    # --- logging ---
    log_level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR or CRITICAL
    log_format: Literal["auto", "json", "console"] = "auto"  # auto: console on a terminal
    environment: str = "development"  # printed on every log line, e.g. production

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
    # Writer model for the first email; blank means LLM_MODEL (same provider, key and address).
    # Research can stay on a cheap model while the email is written by a stronger one.
    llm_copy_model: str = ""
    # "low", "medium" or "high" for a reasoning model that accepts it (OpenRouter's
    # ``reasoning.effort``); blank sends nothing. Reasoning tokens count against LLM_MAX_TOKENS,
    # so a reasoning model with no limit can use the whole budget thinking and cut its answer.
    llm_reasoning_effort: str = ""
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
    # Keys that encrypt workspaces' mailbox tokens and passwords (Phase 6c), as JSON:
    # {"1": "<base64 of 32 bytes>"}; the highest version encrypts. `outbound secrets new-key`.
    secrets_keys: SecretStr = SecretStr("")
    # --- people and their email (Phase 6b) ---
    app_base_url: str = "http://127.0.0.1:8000"  # links in invitations and resets start with it
    superadmin_enabled: bool = True  # alpha only: a superadmin may read any workspace
    terms_version: str = "2026-10"  # the Terms a person accepts when they set a password
    email_from: str = "Outbound <no-reply@localhost>"
    smtp_host: str = ""  # blank: messages go to the log (development)
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    intake_webhook_secret: SecretStr = SecretStr("")  # blank disables the webhook
    cookie_secure: bool = False  # set true when served over https
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    # Proxies whose X-Forwarded-For is trusted, so the login throttle and logs see the real
    # client. "*" is right in the container, whose port is published on the VM's loopback only.
    forwarded_allow_ips: str = "127.0.0.1"

    # --- email waterfall (provisional until the bake-off) ---
    # Finders are tried in this order. OrbiSearch is verify-only, so it cannot be a finder.
    finder_chain: Annotated[list[str], NoDecode] = ["hunter", "zerobounce"]
    verifier: str = "myemailverifier"
    catch_all_resolver: str = "scrubby"

    @model_validator(mode="after")
    def _pick_database(self) -> Settings:
        if not self.database_url:
            if self.database_backend == "sqlite":
                self.database_url = f"sqlite:///{self.sqlite_path}"
            elif self.postgres_url:
                self.database_url = self.postgres_url
                self.platform_database_url = self.platform_database_url or (
                    self.postgres_platform_url
                )
                self.migrate_database_url = self.migrate_database_url or self.postgres_migrate_url
            else:
                raise ValueError("DATABASE_BACKEND is postgres but POSTGRES_URL is not set")
        self.platform_database_url = self.platform_database_url or self.database_url
        self.migrate_database_url = self.migrate_database_url or self.database_url
        return self

    @field_validator("log_level")
    @classmethod
    def _known_log_level(cls, value: str) -> str:
        from outbound.logging import normalise_level

        return normalise_level(value)

    @field_validator("finder_chain", mode="before")
    @classmethod
    def _split_chain(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value
