"""Serve published websites from DevForge at a stable URL (spec §10, §11).

This serves the immutable per-version snapshot for a website's CURRENT version. It
only ever returns files — it executes no customer code — and it refuses any path
that escapes the version's directory (path-traversal guard). This is the working
DevForge URL a customer gets on publish; a public *.devforge.app domain with real
DNS/SSL is the Phase-2 gated path and is not served here.
"""
from __future__ import annotations

import mimetypes
from pathlib import Path

from django.http import FileResponse, Http404, HttpResponse, HttpResponseRedirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.publishing.models import AcmeChallenge, Form, Website


def serve_files_for(website, path: str):
    """Serve one file from a website's current published snapshot (shared by the
    path-based /sites/ route and custom-domain host routing)."""
    version = website.current
    if version is None or not version.artifact_dir:
        raise Http404("This site is not published.")
    root = Path(version.artifact_dir).resolve()
    rel = path or "index.html"
    if rel.endswith("/"):
        rel += "index.html"
    target = (root / rel).resolve()
    if root != target and root not in target.parents:
        raise Http404("Not found.")
    if target.is_dir():
        target = (target / "index.html").resolve()
    if not target.is_file():
        raise Http404("Not found.")
    content_type, _ = mimetypes.guess_type(str(target))
    return FileResponse(open(target, "rb"), content_type=content_type or "application/octet-stream"), content_type


def acme_challenge(request, token):
    """Serve an ACME HTTP-01 challenge response (spec §22). The CA fetches this during
    certificate issuance; we return the stored key authorization as plain text."""
    ch = AcmeChallenge.objects.filter(token=token).first()
    if ch is None:
        raise Http404("Unknown challenge.")
    return HttpResponse(ch.key_authorization, content_type="text/plain")


def serve_published(request, subdomain, path=""):
    website = Website.objects.filter(subdomain=subdomain).first()
    if website is None:
        raise Http404("No such site.")
    response, content_type = serve_files_for(website, path)
    # Count real HTML page views (not assets) — privacy-first, honors Do-Not-Track.
    if (content_type or "").startswith("text/html"):
        from apps.publishing import analytics
        analytics.record_view(website, request)
    return response


@csrf_exempt
@require_POST
def submit_form(request, subdomain, slug):
    """Public form endpoint for published sites (spec §23).

    CSRF-exempt by design: this is a public submission endpoint that static customer
    pages post to (like any SaaS form endpoint). Spam is handled by a honeypot field
    and required-field validation, not a CSRF token. It stores the submission, emails
    a notification (best-effort) and creates a CRM lead.
    """
    from apps.publishing import forms_service as forms
    form = Form.objects.filter(website__subdomain=subdomain, slug=slug, active=True).first()
    if form is None:
        raise Http404("No such form.")
    data = {k: v for k, v in request.POST.items()}
    try:
        forms.submit(form, data)
    except forms.FormError as exc:
        # Re-show the errors plainly (a real generated site would style this).
        items = "".join(f"<li>{e}</li>" for e in exc.errors)
        return HttpResponse(
            f"<h1>Please check the form</h1><ul>{items}</ul><p><a href='javascript:history.back()'>Go back</a></p>",
            status=400,
        )
    if request.headers.get("Accept", "").startswith("application/json"):
        return HttpResponse('{"ok":true}', content_type="application/json")
    # Only redirect within this site — never to an attacker-supplied external URL.
    home = f"/sites/{subdomain}/"
    nxt = request.POST.get("_next") or ""
    safe = nxt if nxt.startswith(home) else home
    return HttpResponseRedirect(safe)
