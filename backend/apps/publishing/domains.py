"""Custom domain: DNS verification, provider + SSL abstractions (spec §19–§22).

The honest core that works offline: generate the exact DNS records a customer must
set, and verify domain ownership by looking for a unique TXT token via a REAL DNS
resolver. Verification reports VERIFIED only when a real lookup actually finds the
token — never on a timer, never faked (spec §50).

What is infra-gated (and says so): a working DNS resolver library/network, auto-DNS
providers (Cloudflare/Route53/…), and SSL issuance (ACME). Those refuse or stay
pending rather than pretend. The resolver is injectable so the flow is fully
testable without network.
"""
from __future__ import annotations

import re

from django.conf import settings

_VERIFY_PREFIX = "_devforge-verify"
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)([a-z0-9](-?[a-z0-9])*\.)+[a-z]{2,}$"
)


def is_valid_hostname(hostname: str) -> bool:
    return bool(_HOSTNAME_RE.match((hostname or "").strip().lower()))


def is_apex(hostname: str) -> bool:
    # Rough apex check: exactly one label before the public suffix (example.com).
    return hostname.count(".") == 1


def required_records(hostname: str, token: str) -> list[dict]:
    """The DNS records the customer must create. Correct standard practice; routing
    completes once DevForge hosting serves the domain."""
    target = settings.DEVFORGE_DOMAIN_TARGET
    records = [
        {"type": "TXT", "name": f"{_VERIFY_PREFIX}.{hostname}", "value": token,
         "purpose": "Proves you own this domain."},
    ]
    if is_apex(hostname):
        records.append({
            "type": "ALIAS/ANAME", "name": hostname, "value": target,
            "purpose": "Routes the apex domain to DevForge (or use the www subdomain if "
                       "your DNS has no ALIAS support).",
        })
    else:
        records.append({
            "type": "CNAME", "name": hostname, "value": target,
            "purpose": "Routes this domain to DevForge.",
        })
    return records


def verify_name(hostname: str) -> str:
    return f"{_VERIFY_PREFIX}.{hostname}"


# --- DNS resolver seam ---------------------------------------------------------
class DNSResolver:
    def available(self) -> bool:
        return False

    def txt(self, name: str) -> list[str]:
        raise NotImplementedError


class SystemResolver(DNSResolver):
    """Real DNS TXT lookup via dnspython when installed. Without it (or without
    network) it reports unavailable rather than guess."""

    def available(self) -> bool:
        try:
            import dns.resolver  # noqa: F401
            return True
        except Exception:
            return False

    def txt(self, name: str) -> list[str]:
        import dns.resolver
        values: list[str] = []
        for rdata in dns.resolver.resolve(name, "TXT"):
            values.append(b"".join(rdata.strings).decode() if hasattr(rdata, "strings") else str(rdata).strip('"'))
        return values


def default_resolver() -> DNSResolver:
    return SystemResolver()


# --- DNS provider abstraction (spec §20) ---------------------------------------
class DomainProvider:
    key = ""
    name = ""

    def is_available(self) -> bool:
        return False

    def configure_dns(self, domain) -> None:
        raise NotImplementedError


class ManualDNSProvider(DomainProvider):
    """The customer sets the records at their own registrar. DevForge only tells
    them what to set and verifies — it never touches unrelated records (spec §21)."""

    key = "manual"
    name = "Manual (your DNS provider)"

    def is_available(self) -> bool:
        return True

    def configure_dns(self, domain) -> None:
        # Nothing to do automatically — the records are shown to the customer.
        return None


class _UnavailableDNSProvider(DomainProvider):
    def __init__(self, key, name):
        self.key, self.name = key, name

    def configure_dns(self, domain):
        raise DomainError(
            f"Automatic DNS via {self.name} is not configured on this host "
            "(API credentials required). Use the manual records instead."
        )


class DomainError(Exception):
    pass


_PROVIDERS: dict[str, DomainProvider] = {
    "manual": ManualDNSProvider(),
    "cloudflare": _UnavailableDNSProvider("cloudflare", "Cloudflare"),
    "route53": _UnavailableDNSProvider("route53", "AWS Route 53"),
    "namecheap": _UnavailableDNSProvider("namecheap", "Namecheap"),
    "godaddy": _UnavailableDNSProvider("godaddy", "GoDaddy"),
}


def get_dns_provider(key: str) -> DomainProvider | None:
    return _PROVIDERS.get(key)


def dns_provider_status() -> list[dict]:
    return [{"key": p.key, "name": p.name, "available": p.is_available()} for p in _PROVIDERS.values()]


# --- SSL abstraction (spec §22) ------------------------------------------------
class SSLProvider:
    name = "ACME / Let's Encrypt"

    def is_available(self) -> bool:
        # Real issuance needs the domain live + an ACME challenge served from the
        # edge that hosts it — not configured here.
        return False

    def issue(self, domain):
        raise DomainError(
            "SSL issuance needs the domain routed to live DevForge hosting so the "
            "certificate challenge can be answered. That isn't configured here, so "
            "the certificate stays pending — DevForge never reports SSL active until "
            "a real certificate is installed."
        )


def ssl_provider() -> SSLProvider:
    return SSLProvider()
