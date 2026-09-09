"""Custom domain orchestration (spec §19, §21, §22).

connect_domain(): validate the hostname, mint a verification token, and record the
exact DNS records the customer must create — no unrelated records are ever touched.
verify_domain(): perform a REAL DNS TXT lookup (via an injectable resolver) and mark
verified only if the token is actually present. request_ssl(): only after
verification; it stays 'pending' because issuance needs the domain live, and never
flips to 'active' without a real certificate.
"""
from __future__ import annotations

import secrets

from django.utils import timezone

from apps.audit.service import record as audit
from apps.publishing import domains
from apps.publishing.models import CustomDomain


class DomainServiceError(Exception):
    pass


def connect_domain(website, *, hostname, user=None, provider="manual") -> CustomDomain:
    hostname = (hostname or "").strip().lower().rstrip(".")
    if hostname.startswith("http://") or hostname.startswith("https://"):
        hostname = hostname.split("://", 1)[1]
    hostname = hostname.split("/", 1)[0]
    if not domains.is_valid_hostname(hostname):
        raise DomainServiceError(f"'{hostname}' is not a valid domain name.")
    if CustomDomain.objects.filter(hostname=hostname).exists():
        raise DomainServiceError(f"{hostname} is already connected to a DevForge site.")
    if domains.get_dns_provider(provider) is None:
        raise DomainServiceError(f"Unknown DNS provider '{provider}'.")

    token = "devforge-verify=" + secrets.token_urlsafe(24)
    domain = CustomDomain.objects.create(
        website=website, hostname=hostname, provider=provider,
        verification_token=token, required_records=domains.required_records(hostname, token),
        detail="Add the DNS records below, then verify.",
    )
    audit("domain.connect", actor=user, organization=website.project.organization,
          target=f"domain:{domain.id}", summary=hostname)
    return domain


def verify_domain(domain: CustomDomain, *, resolver=None, user=None) -> CustomDomain:
    resolver = resolver or domains.default_resolver()
    domain.last_checked = timezone.now()

    if not resolver.available():
        domain.detail = ("DNS could not be checked on this host (no resolver/network). "
                         "The domain stays unverified until a real DNS check succeeds.")
        domain.save(update_fields=["last_checked", "detail"])
        return domain

    name = domains.verify_name(domain.hostname)
    try:
        values = resolver.txt(name)
    except Exception as exc:
        domain.verification_status = CustomDomain.VERIFY_FAILED
        domain.detail = f"DNS lookup failed for {name}: {exc}"[:500]
        domain.save(update_fields=["verification_status", "last_checked", "detail"])
        return domain

    if any(domain.verification_token in v for v in values):
        domain.verification_status = CustomDomain.VERIFY_VERIFIED
        domain.verified_at = timezone.now()
        domain.detail = "Ownership verified."
        # Ownership is proven; SSL can now be requested (it will stay pending offline).
        if domain.ssl_status == CustomDomain.SSL_NONE:
            domain.ssl_status = CustomDomain.SSL_PENDING
        domain.save(update_fields=["verification_status", "verified_at", "detail",
                                   "ssl_status", "last_checked"])
        audit("domain.verified", actor=user, organization=domain.website.project.organization,
              target=f"domain:{domain.id}", summary=domain.hostname)
    else:
        domain.verification_status = CustomDomain.VERIFY_FAILED
        domain.detail = (f"The verification record wasn't found yet at {name}. "
                         "DNS can take time to propagate — try again shortly.")
        domain.save(update_fields=["verification_status", "detail", "last_checked"])
    return domain


def request_ssl(domain: CustomDomain, *, user=None) -> CustomDomain:
    if not domain.is_verified:
        raise DomainServiceError("Verify domain ownership before requesting a certificate.")
    provider = domains.ssl_provider()
    try:
        provider.issue(domain)
        domain.ssl_status = CustomDomain.SSL_ACTIVE   # only reached with a real cert
        domain.detail = "Certificate installed."
    except domains.DomainError as exc:
        domain.ssl_status = CustomDomain.SSL_PENDING
        domain.detail = str(exc)
    domain.save(update_fields=["ssl_status", "detail"])
    audit("domain.ssl_request", actor=user, organization=domain.website.project.organization,
          target=f"domain:{domain.id}", summary=domain.ssl_status)
    return domain


def remove_domain(domain: CustomDomain, *, user=None) -> None:
    website = domain.website
    host = domain.hostname
    domain.delete()
    audit("domain.remove", actor=user, organization=website.project.organization,
          target=f"website:{website.id}", summary=host)
