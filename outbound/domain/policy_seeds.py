"""Country policy version 1: what the plan's compliance table says, as data.

These are working defaults for design, not legal advice. Rows are seeded with no reviewer;
a lawyer confirms them (and sets ``reviewed_by``) before automatic sending is switched on.
Footer templates keep ``{placeholders}`` that the copy stage fills from the sender profile.
"""

from __future__ import annotations

from outbound.domain.entities import CountryPolicy
from outbound.domain.enums import PolicyRule, Provenance

_OPT_OUT = 'Reply "unsubscribe" and we will stop.'

_US_FOOTER = "{sender_legal_name}, {postal_address}. " + _OPT_OUT
_UK_FOOTER = (
    "{sender_legal_name}, {registration_details}. We found your work address on {data_source} "
    "and wrote because this relates to your role. " + _OPT_OUT + " You may also object to us "
    "holding your details."
)
_EU_FOOTER = (
    "{sender_legal_name}, {postal_address}. Your work address came from {data_source}; we wrote "
    "under legitimate interest because this relates to your role. " + _OPT_OUT
)
_CA_FOOTER = (
    "{sender_legal_name}, {postal_address}, {contact_info}. Unsubscribe at no cost: " + _OPT_OUT
)

_ALLOW = PolicyRule.ALLOW_WITH_FOOTER

DEFAULT_COUNTRY_POLICIES: tuple[CountryPolicy, ...] = (
    CountryPolicy("US", _ALLOW, footer_template=_US_FOOTER),  # CAN-SPAM: opt-out regime
    CountryPolicy(  # PECR: corporate subscribers only
        "GB", _ALLOW, requires_corporate_subscriber=True, footer_template=_UK_FOOTER
    ),
    CountryPolicy("DE", PolicyRule.BLOCK),  # UWG section 7: prior express consent, even B2B
    CountryPolicy("AT", PolicyRule.BLOCK),
    CountryPolicy("FR", _ALLOW, footer_template=_EU_FOOTER),  # B2B legitimate interest
    CountryPolicy("NL", _ALLOW, footer_template=_EU_FOOTER),
    CountryPolicy("IE", _ALLOW, footer_template=_EU_FOOTER),
    CountryPolicy("SE", _ALLOW, footer_template=_EU_FOOTER),
    CountryPolicy(  # CASL: implied consent only for published or operator-given addresses
        "CA",
        _ALLOW,
        allowed_provenance=(Provenance.OPERATOR_GIVEN, Provenance.PUBLICLY_PUBLISHED),
        footer_template=_CA_FOOTER,
    ),
    CountryPolicy("IN", PolicyRule.CONSENT_REQUIRED),  # DPDP Act: consent-based
    CountryPolicy(
        "ZZ", PolicyRule.CONSENT_REQUIRED
    ),  # unknown country (held by the decision logic)
)
