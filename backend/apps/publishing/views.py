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

from django.http import FileResponse, Http404

from apps.publishing.models import Website


def serve_published(request, subdomain, path=""):
    website = Website.objects.filter(subdomain=subdomain).first()
    if website is None:
        raise Http404("No such site.")
    version = website.current
    if version is None or not version.artifact_dir:
        raise Http404("This site is not published.")

    root = Path(version.artifact_dir).resolve()
    rel = path or "index.html"
    if rel.endswith("/"):
        rel += "index.html"
    target = (root / rel).resolve()
    # Traversal guard: the resolved target must stay inside the version directory.
    if root != target and root not in target.parents:
        raise Http404("Not found.")
    if target.is_dir():
        target = (target / "index.html").resolve()
    if not target.is_file():
        raise Http404("Not found.")

    content_type, _ = mimetypes.guess_type(str(target))
    return FileResponse(open(target, "rb"), content_type=content_type or "application/octet-stream")
