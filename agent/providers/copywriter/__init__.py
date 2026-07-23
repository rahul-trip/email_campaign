"""agent/providers/copywriter/__init__.py — Factory / Registry for copywriter providers."""

from __future__ import annotations

from agent.providers.discovery.base import ProviderError
from .base import CopyOutput, CopywriterProvider
from .llm_copywriter import LlmCopywriter
from .template_stub import TemplateCopywriter

_REGISTRY: dict[str, type[CopywriterProvider]] = {
    "template": TemplateCopywriter,
    "llm": LlmCopywriter,
}


def get_copywriter(name: str, **kwargs) -> CopywriterProvider:
    """Return the concrete copywriter for *name*.

    "llm" requires llm= (LlmConfig) and sender= (SenderProfile) kwargs;
    the concrete adapter and its API key/model come from llm.provider /
    llm.model, not from *name* — see llm_copywriter.py's _PROVIDER_PRESETS.
    """
    cls = _REGISTRY.get(name)
    if cls is None:
        raise ProviderError(f"Unknown copywriter {name!r}. Available: {list(_REGISTRY)}")
    if cls is LlmCopywriter:
        return LlmCopywriter(
            llm=kwargs["llm"],
            sender=kwargs["sender"],
            per_call_delay_seconds=kwargs.get("per_call_delay_seconds", 1.0),
        )
    return cls()


__all__ = ["CopyOutput", "CopywriterProvider", "get_copywriter"]
