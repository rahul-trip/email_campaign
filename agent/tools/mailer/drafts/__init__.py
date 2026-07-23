"""Provider registry.

Add a new provider by writing a class that implements `drafts.base.DraftProvider`
and registering it here under a new PROVIDER_TYPE key. Nothing else in the
codebase needs to change.
"""

from __future__ import annotations

from agent.tools.mailer.config.settings import Settings
from agent.tools.mailer.drafts.base import DraftProvider
from agent.tools.mailer.drafts.imap_provider import ImapDraftProvider

_PROVIDERS: dict[str, type[DraftProvider]] = {
    "imap": ImapDraftProvider,
}


def get_provider(settings: Settings) -> DraftProvider:
    try:
        provider_cls = _PROVIDERS[settings.provider_type]
    except KeyError as exc:
        raise ValueError(
            f"Unknown PROVIDER_TYPE={settings.provider_type!r}. "
            f"Available: {list(_PROVIDERS)}"
        ) from exc
    return provider_cls(settings)
