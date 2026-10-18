"""Can mail from this domain be trusted by receivers? SPF, DKIM and DMARC records, checked.

Missing records are the commonest reason cold email lands in spam, so the settings screen shows
the result and the send switch (Phase 5) refuses to turn on while they fail. The lookup is
injected so tests need no network.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass

TxtLookup = Callable[[str], list[str]]

COMMON_DKIM_SELECTORS = ("default", "google", "selector1", "selector2", "k1", "mail", "s1", "dkim")


@dataclass(frozen=True)
class RecordCheck:
    name: str
    ok: bool
    detail: str
    record: str | None = None


@dataclass(frozen=True)
class DnsReport:
    domain: str
    spf: RecordCheck
    dkim: RecordCheck
    dmarc: RecordCheck

    @property
    def ok(self) -> bool:
        return self.spf.ok and self.dkim.ok and self.dmarc.ok

    def to_json(self) -> dict[str, object]:
        return {"domain": self.domain, "ok": self.ok, **{k: asdict(v) for k, v in self._parts()}}

    def _parts(self) -> list[tuple[str, RecordCheck]]:
        return [("spf", self.spf), ("dkim", self.dkim), ("dmarc", self.dmarc)]


def system_lookup(name: str) -> list[str]:
    """TXT records for ``name`` using the machine's resolver; empty if there are none."""
    import dns.exception
    import dns.resolver

    try:
        answer = dns.resolver.resolve(name, "TXT", lifetime=5.0)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
        return []
    except dns.exception.DNSException:
        return []
    return ["".join(part.decode() for part in record.strings) for record in answer]


def check_domain(
    domain: str,
    lookup: TxtLookup = system_lookup,
    selectors: Sequence[str] = COMMON_DKIM_SELECTORS,
) -> DnsReport:
    domain = domain.strip().lower()
    return DnsReport(
        domain, _spf(domain, lookup), _dkim(domain, lookup, selectors), _dmarc(domain, lookup)
    )


def _spf(domain: str, lookup: TxtLookup) -> RecordCheck:
    records = [r for r in lookup(domain) if r.lower().startswith("v=spf1")]
    if not records:
        return RecordCheck("spf", False, "no SPF record: add a TXT record starting v=spf1")
    if len(records) > 1:
        return RecordCheck(
            "spf", False, "more than one SPF record: receivers reject this", records[0]
        )
    return RecordCheck("spf", True, "SPF record found", records[0])


def _dkim(domain: str, lookup: TxtLookup, selectors: Sequence[str]) -> RecordCheck:
    for selector in selectors:
        found = [r for r in lookup(f"{selector}._domainkey.{domain}") if "p=" in r]
        if found:
            return RecordCheck("dkim", True, f"DKIM key found for selector {selector!r}", found[0])
    return RecordCheck(
        "dkim", False, "no DKIM key at a common selector: check your mail provider's setup page"
    )


def _dmarc(domain: str, lookup: TxtLookup) -> RecordCheck:
    records = [r for r in lookup(f"_dmarc.{domain}") if r.lower().startswith("v=dmarc1")]
    if not records:
        return RecordCheck("dmarc", False, "no DMARC record: add a TXT record at _dmarc")
    policy = next(
        (p.split("=")[1] for p in records[0].replace(" ", "").split(";") if p.startswith("p=")), ""
    )
    if policy.lower() == "none":
        return RecordCheck("dmarc", True, "DMARC found, policy none (monitoring only)", records[0])
    return RecordCheck("dmarc", True, f"DMARC found, policy {policy}", records[0])
