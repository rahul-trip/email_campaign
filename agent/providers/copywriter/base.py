"""agent/providers/copywriter/base.py — Strategy ABC for copy generation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from agent.domain.models import Company, Contact


@dataclass(frozen=True)
class CopyOutput:
    """The three copy blocks generated for a lead."""

    pitch_email: str      # Full tailored pitch body
    follow_up: str        # Shorter follow-up text
    commonalities: str    # Points of commonality / synergies bullets


class CopywriterProvider(ABC):
    """Strategy interface for generating outbound email copy.

    Implementations:
        template_stub.TemplateCopywriter — deterministic template (default)
        [future] ClaudeCopywriter / OpenAICopywriter — LLM-based

    See system_specification.md Module C for the negative-constraint prompt
    directives that any LLM-based adapter must honor.
    """

    @abstractmethod
    def write(self, company: Company, contact: Contact, config: "AgentConfig") -> CopyOutput:  # noqa: F821
        """Generate pitch_email, follow_up, and commonalities for the lead.

        Args:
            company: The target company.
            contact: The resolved POC.
            config:  The full AgentConfig (for signature_name, signature_title, etc.).

        Returns:
            A CopyOutput with all three text blocks populated.
        """
        ...
