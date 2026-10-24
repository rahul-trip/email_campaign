"""Can mail from this domain be trusted by receivers? SPF, DKIM and DMARC records, checked.

Missing records are the commonest reason cold email lands in spam, so the settings screen shows
the result and the send switch (Phase 5) refuses to turn on while they fail. The lookup is
injected so tests need no network.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass

TxtLookup = Callable[[str], list[str]]
MxLookup = Callable[[str], list[str]]

COMMON_DKIM_SELECTORS = ("default", "google", "selector1", "selector2", "k1", "mail", "s1", "dkim")
# Where each provider publishes its DKIM keys, tried before the common names.
PROVIDER_SELECTORS = {
    "gmail": ("google",),
    "graph": ("selector1", "selector2"),
}
SPF_LOOKUP_LIMIT = 10  # RFC 7208 §4.6.4: more than this and receivers return a permanent error


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
    mx: RecordCheck | None = None  # only when the caller could look up MX records

    @property
    def ok(self) -> bool:
        return all(part.ok for _, part in self._parts())

    def to_json(self) -> dict[str, object]:
        return {"domain": self.domain, "ok": self.ok, **{k: asdict(v) for k, v in self._parts()}}

    def _parts(self) -> list[tuple[str, RecordCheck]]:
        parts = [("spf", self.spf), ("dkim", self.dkim), ("dmarc", self.dmarc)]
        return [("mx", self.mx), *parts] if self.mx else parts


def _resolve(name: str, kind: str) -> list[str]:
    import dns.exception
    import dns.resolver

    try:
        answer = dns.resolver.resolve(name, kind, lifetime=5.0)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
        return []
    except dns.exception.DNSException:
        return []
    if kind == "TXT":
        return ["".join(part.decode() for part in record.strings) for record in answer]
    return [str(record.exchange).rstrip(".") for record in answer]


def system_lookup(name: str) -> list[str]:
    """TXT records for ``name`` using the machine's resolver; empty if there are none."""
    return _resolve(name, "TXT")


def system_mx(name: str) -> list[str]:
    """Mail servers (MX) for ``name``; empty if there are none."""
    return _resolve(name, "MX")


def check_domain(
    domain: str,
    lookup: TxtLookup = system_lookup,
    selectors: Sequence[str] = COMMON_DKIM_SELECTORS,
    *,
    mx_lookup: MxLookup | None = None,
    gateway: str | None = None,
) -> DnsReport:
    """``selectors`` are extra DKIM names to try (one the person entered); the provider's own
    (``gateway``: ``gmail`` or ``graph``) come first. Without ``mx_lookup`` MX is not checked."""
    domain = domain.strip().lower()
    names = list(dict.fromkeys([*selectors, *PROVIDER_SELECTORS.get(gateway or "", ())]))
    names.sort(key=lambda n: n not in PROVIDER_SELECTORS.get(gateway or "", ()))
    return DnsReport(
        domain,
        _spf(domain, lookup),
        _dkim(domain, lookup, names),
        _dmarc(domain, lookup),
        _mx(domain, mx_lookup) if mx_lookup else None,
    )


def _mx(domain: str, mx_lookup: MxLookup) -> RecordCheck:
    servers = mx_lookup(domain)
    if not servers:
        return RecordCheck(
            "mx", False,
            "no mail servers (MX): replies could not reach this domain; "
            "add the MX records your mail provider lists",
        )  # fmt: skip
    return RecordCheck("mx", True, f"{len(servers)} mail server(s): {', '.join(servers[:3])}")


PLAIN_MECHANISMS = ("a", "mx", "ptr")
COUNTED_PREFIXES = ("a:", "a/", "mx:", "mx/", "ptr:", "exists:")


def spf_lookups(
    record: str, lookup: TxtLookup, *, depth: int = 0, seen: set[str] | None = None
) -> int:
    """DNS lookups an SPF record makes when a receiver evaluates it: ``include``, ``a``, ``mx``,
    ``ptr``, ``exists`` and ``redirect`` each count one, and included records add their own."""
    seen = seen if seen is not None else set()
    total = 0
    for term in record.split()[1:]:
        word = term.lstrip("+-~?").lower()
        if word.startswith(("include:", "redirect=")):
            target = word.split(":", 1)[1] if word.startswith("include:") else word.split("=", 1)[1]
            total += 1
            if depth < SPF_LOOKUP_LIMIT and target not in seen:
                seen.add(target)
                inner = next((r for r in lookup(target) if r.lower().startswith("v=spf1")), None)
                if inner:
                    total += spf_lookups(inner, lookup, depth=depth + 1, seen=seen)
        elif word in PLAIN_MECHANISMS or word.startswith(COUNTED_PREFIXES):
            total += 1
    return total


def _spf(domain: str, lookup: TxtLookup) -> RecordCheck:
    records = [r for r in lookup(domain) if r.lower().startswith("v=spf1")]
    if not records:
        return RecordCheck("spf", False, "no SPF record: add a TXT record starting v=spf1")
    if len(records) > 1:
        return RecordCheck(
            "spf", False,
            "more than one SPF record: receivers reject this; merge them into a single record",
            records[0],
        )  # fmt: skip
    count = spf_lookups(records[0], lookup)
    if count > SPF_LOOKUP_LIMIT:
        return RecordCheck(
            "spf", False,
            f"SPF needs {count} DNS lookups and receivers allow {SPF_LOOKUP_LIMIT}: it fails. "
            "Remove services you no longer send through, or flatten the record",
            records[0],
        )  # fmt: skip
    return RecordCheck(
        "spf", True, f"SPF record found ({count} of {SPF_LOOKUP_LIMIT} lookups)", records[0]
    )


def _dkim(domain: str, lookup: TxtLookup, selectors: Sequence[str]) -> RecordCheck:
    for selector in selectors:
        found = [r for r in lookup(f"{selector}._domainkey.{domain}") if "p=" in r]
        if found:
            return RecordCheck("dkim", True, f"DKIM key found for selector {selector!r}", found[0])
    return RecordCheck(
        "dkim", False,
        "no DKIM key at a common selector: switch DKIM on in your mail provider's admin "
        "settings and publish the record it gives you (Google: selector google; "
        "Microsoft 365: selector1 and selector2)",
    )  # fmt: skip


def _dmarc(domain: str, lookup: TxtLookup) -> RecordCheck:
    records = [r for r in lookup(f"_dmarc.{domain}") if r.lower().startswith("v=dmarc1")]
    if not records:
        return RecordCheck(
            "dmarc", False,
            "no DMARC record: add a TXT record at _dmarc with "
            f"v=DMARC1; p=none; rua=mailto:dmarc@{domain}",
        )  # fmt: skip
    tags = dict(
        part.split("=", 1) for part in records[0].replace(" ", "").split(";") if "=" in part
    )
    policy = tags.get("p", "").lower()
    reports = "" if tags.get("rua") else "; add rua=mailto:... to receive reports"
    if policy == "none":
        return RecordCheck(
            "dmarc", True, f"DMARC found, policy none (monitoring only){reports}", records[0]
        )
    return RecordCheck("dmarc", True, f"DMARC found, policy {policy}{reports}", records[0])
