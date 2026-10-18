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


@dataclass(frozen=True)
class CountryInference:
    code: str | None
    evidence: str
    strong: bool  # strong evidence may set the country; weak evidence is only a suggestion


NO_COUNTRY = CountryInference(None, "", strong=False)


def infer_country(domain: str, text: str) -> CountryInference:
    """What the pages say about the country.

    Strong evidence is a stated registration or a country-code domain. A phone prefix or a
    postcode is weak: a German company can have a London office, and the country decides which
    law applies, so weak evidence is only offered to the operator as a suggestion.
    """
    registered = _REGISTERED_IN.search(text)
    if registered:
        return CountryInference(
            "GB", f"site says it is registered in {registered.group(1).title()}", strong=True
        )
    tld = domain.rsplit(".", 1)[-1].lower()
    if tld in _TLD_COUNTRY:
        return CountryInference(_TLD_COUNTRY[tld], f"the .{tld} domain", strong=True)
    for prefix, code in _PHONE_COUNTRY:
        if prefix in text.replace(" ", ""):
            return CountryInference(code, f"a {prefix} phone number on the site", strong=False)
    if _UK_POSTCODE.search(text):
        return CountryInference("GB", "a UK postcode on the site", strong=False)
    return NO_COUNTRY


_LEGAL_FORM = r"(?:Ltd\.?|Limited|LLP|PLC)"
_NAME_SUFFIX = re.compile(rf"[\s,.]+{_LEGAL_FORM}\s*$", re.IGNORECASE)
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


def _own_name_patterns(company_name: str, domain: str) -> list[re.Pattern[str]]:
    """Patterns for "<this company's name> Ltd", from the name and from the domain's label."""
    name = _NAME_SUFFIX.sub("", company_name.strip())
    spellings: list[str] = []
    if len(name) >= 3:
        spellings.append(r"\s+".join(re.escape(word) for word in name.split()))
    label = re.sub(r"[^a-z0-9]", "", domain.split(".")[0].lower())
    if len(label) >= 4:  # "openclimatefix" also matches "Open Climate Fix" and "Open-Climate-Fix"
        spellings.append(r"[\s-]*".join(re.escape(char) for char in label))
    return [
        re.compile(rf"(?<![A-Za-z0-9])(?:{spelling})[\s,.]*(?:{_LEGAL_FORM})(?![A-Za-z0-9])", re.I)
        for spelling in spellings
    ]


def find_incorporation_markers(
    text: str, company_name: str = "", domain: str = ""
) -> IncorporationMarkers:
    """Signs on the site that THIS company is incorporated.

    A legal form counts only straight after the company's own name ("Acme Energy Ltd"). A
    bare "Ltd" elsewhere on a page usually belongs to a partner, a client or a supplier, and
    counting it could make us email a sole trader, which UK law forbids.
    """
    form: str | None = None
    for pattern in _own_name_patterns(company_name, domain):
        found = pattern.search(text)
        if found:
            form = found.group(0).strip()
            break
    number = _COMPANY_NUMBER.search(text)
    return IncorporationMarkers(
        legal_form=form,
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
