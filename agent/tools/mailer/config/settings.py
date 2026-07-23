"""Central configuration, loaded from environment variables / a .env file.

This is the one place that knows about the active mail provider's connection
details. Everything downstream (ingestion, message building, the campaign
runner) only ever sees a `Settings` object — never raw env vars — so adding a
new provider later means adding fields here and a new class under drafts/,
not touching the rest of the codebase.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Secrets live in agent/.env (shared by the agent's own providers and mailer),
# with an optional project-root .env as a lower-priority fallback. Mirrors the
# same load order as agent/config/loader.py.
_AGENT_ROOT = Path(__file__).resolve().parent.parent.parent  # .../agent
_PROJECT_ROOT = _AGENT_ROOT.parent  # .../email_capaign
load_dotenv(_PROJECT_ROOT / ".env", override=False)
load_dotenv(_AGENT_ROOT / ".env", override=True)


def _env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    val = os.getenv(name)
    return float(val) if val else default


def _env_int(name: str, default: int) -> int:
    val = os.getenv(name)
    return int(val) if val else default


@dataclass(frozen=True)
class Settings:
    provider_type: str
    imap_host: str
    imap_port: int
    imap_use_ssl: bool
    email_address: str
    email_password: str
    drafts_folder: str
    from_name: str
    xlsx_path: str
    delay_seconds: float

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            provider_type=os.getenv("PROVIDER_TYPE", "imap"),
            imap_host=os.getenv("IMAP_HOST", ""),
            imap_port=_env_int("IMAP_PORT", 993),
            imap_use_ssl=_env_bool("IMAP_USE_SSL", True),
            email_address=os.getenv("EMAIL_ADDRESS", ""),
            email_password=os.getenv("EMAIL_PASSWORD", ""),
            drafts_folder=os.getenv("DRAFTS_FOLDER", "Drafts"),
            from_name=os.getenv("FROM_NAME", ""),
            xlsx_path=os.getenv(
                "XLSX_PATH",
                str(_PROJECT_ROOT / "Quantra_Energy_Outbound_Campaign_Matrix.xlsx"),
            ),
            delay_seconds=_env_float("DELAY_SECONDS", 1.0),
        )

    def validate(self, *, require_credentials: bool = True) -> list[str]:
        """Return a list of human-readable problems; empty list means OK.

        `require_credentials=False` is used for dry runs, where we want to
        preview what *would* be drafted without needing mailbox credentials set
        up yet.
        """
        problems = []
        if self.provider_type != "imap":
            problems.append(
                f"Unsupported PROVIDER_TYPE={self.provider_type!r} (only 'imap' is implemented)"
            )
        if require_credentials:
            if not self.imap_host:
                problems.append("IMAP_HOST is not set")
            if not self.email_address:
                problems.append("EMAIL_ADDRESS is not set")
            if not self.email_password:
                problems.append("EMAIL_PASSWORD is not set")
            if not self.drafts_folder:
                problems.append("DRAFTS_FOLDER is not set")
        if not os.path.exists(self.xlsx_path):
            problems.append(f"XLSX_PATH does not exist: {self.xlsx_path}")
        return problems
