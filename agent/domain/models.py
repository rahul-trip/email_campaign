"""agent/domain/models.py — immutable domain dataclasses.

These are the currency passed between LangGraph nodes. Vendor JSON never leaks
past a provider adapter — all adapters map their raw response into these types.

Design note (Strategy / Adapter):
    Providers return Company / Contact / VerifiedEmail directly. The rest of the
    graph (nodes, repository) only imports from here — never from vendor-specific
    modules. Swapping a provider therefore requires zero changes to nodes.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Core domain types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Company:
    """A discovered target company."""

    name: str
    domain: str           # root domain, e.g. "openclimatefix.org"
    url: str              # homepage / contact URL
    description: str = ""


@dataclass(frozen=True)
class Contact:
    """The best point-of-contact at a company."""

    full_name: str
    title: str
    linkedin_url: str = ""
    eccentricities: str = ""  # notes / quirks for the "POC Details" column


@dataclass(frozen=True)
class VerifiedEmail:
    """An email address after NeverBounce verification."""

    address: str
    status: str   # normalized: "valid" | "catchall" | "unknown" | "invalid"
    risky: bool   # True when status is in config.mark_risky_statuses


@dataclass(frozen=True)
class Lead:
    """A complete lead ready to be written to the xlsx.

    copy fields start empty and are filled by the copywriter node.
    """

    company: Company
    contact: Contact
    email: VerifiedEmail

    # Copywriter-generated fields (filled by generate_copy node)
    pitch_email: str = ""
    follow_up: str = ""
    commonalities: str = ""

    def to_row(self) -> dict[str, str]:
        """Produce exactly the 7-column dict expected by XlsxLeadRepository.

        Formatting mirrors the existing rows in the workbook:
        - Organization URL    : "Company Name\\nhttps://..."
        - Specific Person     : "Full Name\\n(Title)"
        - POC Details         : eccentricities string
        - Direct Business Email: plain address
        - Tailored Pitch Email : full body
        - Follow-up Text       : shorter follow-up body
        - Points of Commonality: bullet-style commonalities block
        """
        return {
            COLUMN_ORDER[0]: f"{self.company.name}\n{self.company.url}",
            COLUMN_ORDER[1]: f"{self.contact.full_name}\n({self.contact.title})",
            COLUMN_ORDER[2]: self.contact.eccentricities,
            COLUMN_ORDER[3]: self.email.address,
            COLUMN_ORDER[4]: self.pitch_email,
            COLUMN_ORDER[5]: self.follow_up,
            COLUMN_ORDER[6]: self.commonalities,
        }


# ---------------------------------------------------------------------------
# Column layout — single source of truth for the xlsx writer
# ---------------------------------------------------------------------------

COLUMN_ORDER: list[str] = [
    "Organization URL",
    "Specific Person to Contact",
    "POC Details & Eccentricities",
    "Direct Business Email",
    "Tailored Pitch Email",
    "Follow-up Text",
    "Points of Commonality",
]
