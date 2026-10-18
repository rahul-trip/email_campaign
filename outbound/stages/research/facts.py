"""What can be worked out from page text without asking a model.

Country and legal-entity rules are the compliance basis for who may be emailed, so they are
plain code with tests rather than a model's opinion.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from outbound.domain.enums import LegalEntityType
from outbound.providers.ports import RegistryEntry

_TLD_COUNTRY = {
    "uk": "GB", "de": "DE", "at": "AT", "fr": "FR", "nl": "NL", "ie": "IE", "se": "SE",
    "ca": "CA", "in": "IN", "us": "US",
}  # fmt: skip
_PHONE_COUNTRY = (
    ("+353", "IE"), ("+44", "GB"), ("+49", "DE"), ("+43", "AT"), ("+33", "FR"),
    ("+31", "NL"), ("+46", "SE"), ("+91", "IN"),
)  # fmt: skip
_REGISTERED_IN = re.compile(
    r"registered\s+(?:in|office\s+in)\s+(england|scotland|wales|northern ireland)", re.I
)
_UK_POSTCODE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b")


def infer_country(domain: str, text: str) -> tuple[str | None, str]:
    """An ISO code and the evidence for it, or ``(None, "")``. Strongest signal first."""
    registered = _REGISTERED_IN.search(text)
    if registered:
        return "GB", f"site says it is registered in {registered.group(1).title()}"
    tld = domain.rsplit(".", 1)[-1].lower()
    if tld in _TLD_COUNTRY:
        return _TLD_COUNTRY[tld], f"the .{tld} domain"
    for prefix, code in _PHONE_COUNTRY:
        if prefix in text.replace(" ", ""):
            return code, f"a {prefix} phone number on the site"
    if _UK_POSTCODE.search(text):
        return "GB", "a UK postcode on the site"
    return None, ""


_LEGAL_FORM = re.compile(r"\b(?:Ltd\.?|Limited|LLP|PLC|plc)\b")
_COMPANY_NUMBER = re.compile(
    r"(?:company|registration|registered)\s*(?:no\.?|number|#)?\s*[:.]?\s*((?:[A-Z]{2})?\d{6,8})\b",
    re.I,
)
_SOLE_TRADER = re.compile(r"\bsole\s+trader\b|\btrading\s+as\b|\bt/a\b", re.I)

# Companies House types that are corporate subscribers under PECR: companies, LLPs and
# Scottish partnerships. Ordinary partnerships and sole traders are not on this list.
CORPORATE_TYPES = frozenset(
    {
        "ltd", "plc", "llp", "private-unlimited", "private-unlimited-nsc",
        "private-limited-guarant-nsc", "private-limited-guarant-nsc-limited-exemption",
        "old-public-company", "scottish-partnership", "uk-establishment",
        "registered-society-non-jurisdictional",
    }
)  # fmt: skip


@dataclass(frozen=True)
class IncorporationMarkers:
    legal_form: str | None
    company_number: str | None
    sole_trader_hint: bool

    @property
    def found(self) -> bool:
        return bool(self.legal_form or self.company_number)


def find_incorporation_markers(text: str) -> IncorporationMarkers:
    form = _LEGAL_FORM.search(text)
    number = _COMPANY_NUMBER.search(text)
    return IncorporationMarkers(
        legal_form=form.group(0) if form else None,
        company_number=number.group(1).upper() if number else None,
        sole_trader_hint=bool(_SOLE_TRADER.search(text)),
    )


def _tokens(name: str) -> set[str]:
    noise = {"ltd", "limited", "llp", "plc", "the", "and", "group", "holdings", "uk"}
    return {t for t in re.findall(r"[a-z0-9]+", name.lower()) if t not in noise}


def best_registry_match(name: str, entries: Sequence[RegistryEntry]) -> RegistryEntry | None:
    """The first active entry whose name contains every distinctive word of ``name``."""
    wanted = _tokens(name)
    if not wanted:
        return None
    for entry in entries:
        if entry.status.lower() == "active" and wanted <= _tokens(entry.name):
            return entry
    return None


def classify_legal_entity(
    markers: IncorporationMarkers, match: RegistryEntry | None
) -> tuple[LegalEntityType, str]:
    """Corporate subscriber only on positive evidence; otherwise unknown, so the gate holds."""
    if match is not None and match.company_type in CORPORATE_TYPES:
        return (
            LegalEntityType.CORPORATE_SUBSCRIBER,
            f"active {match.company_type} at Companies House, no. {match.number}",
        )
    if markers.found:
        shown = markers.company_number or markers.legal_form
        return LegalEntityType.CORPORATE_SUBSCRIBER, f"incorporation marker on the site: {shown}"
    if markers.sole_trader_hint:
        return LegalEntityType.SOLE_TRADER_OR_PARTNERSHIP, "the site describes a sole trader"
    return LegalEntityType.UNKNOWN, "no incorporation marker and no Companies House match"
