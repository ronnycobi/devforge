"""Custom-domain host routing (spec §19, §40).

When a request arrives on a customer's own domain (e.g. www.acme.com) that is
VERIFIED in DevForge, serve that website's current published snapshot — real
Host-header virtual hosting. This is what makes a verified custom domain actually
serve the site once DevForge is deployed publicly with the domain pointed at it.

Honest scope: only domains that are verified in our database are served (a
controlled allowlist), and only their published files (no code execution). Requests
on the platform's own host fall through to normal routing. The ACME challenge path is
always allowed through so certificate issuance can complete.
"""
from __future__ import annotations

from django.conf import settings

from apps.publishing.models import CustomDomain
from apps.publishing.views import acme_challenge, serve_files_for


class CustomDomainMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def _host(self, request) -> str:
        raw = request.META.get("HTTP_HOST", "")
        return raw.split(":")[0].strip().lower()

    def __call__(self, request):
        host = self._host(request)
        # Requests to the platform's own hosts use normal routing.
        platform_hosts = set(settings.ALLOWED_HOSTS) | {"localhost", "127.0.0.1", "testserver"}
        base = getattr(settings, "DEVFORGE_BASE_DOMAIN", "")
        if not host or host in platform_hosts or (base and host.endswith("." + base)) or host == base:
            return self.get_response(request)

        domain = CustomDomain.objects.filter(
            hostname=host, verification_status=CustomDomain.VERIFY_VERIFIED
        ).select_related("website").first()
        if domain is None:
            return self.get_response(request)   # unknown/unverified domain → normal routing

        # Always let the CA reach the ACME challenge (HTTP-01) for SSL issuance.
        if request.path.startswith("/.well-known/acme-challenge/"):
            token = request.path.rsplit("/", 1)[-1]
            return acme_challenge(request, token)

        path = request.path.lstrip("/")
        response, _ = serve_files_for(domain.website, path)
        return response
