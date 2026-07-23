"""Provider-agnostic interface for pushing a message into a mailbox's Drafts folder.

Any new provider (Gmail API, Outlook/Graph API, another IMAP host, ...) only needs
to implement this interface. Nothing in ingestion/ or core/ needs to change when
the provider changes — only config.settings.PROVIDER_TYPE and the provider
registration in drafts/__init__.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class DraftProvider(ABC):
    """Abstract base for anything that can save a draft email to a mailbox."""

    def __enter__(self) -> "DraftProvider":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    @abstractmethod
    def connect(self) -> None:
        """Open the connection/session to the mail provider."""

    @abstractmethod
    def close(self) -> None:
        """Close the connection/session cleanly."""

    @abstractmethod
    def save_draft(self, *, to_addr: str, subject: str, body: str) -> str:
        """Save one draft message. Returns a provider-specific identifier for logging."""
