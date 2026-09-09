"""Website publishing orchestration (spec §4, §12, §15, §17, §18, §41, §50).

publish(): compute readiness → build the site into an immutable versioned snapshot
via the host → serve it at a working DevForge URL → real health check → mark LIVE
and make it the current version. If the build produces nothing servable, it fails
honestly (state FAILED) rather than showing a fake "Live".

rollback(): re-point the current version to a previous LIVE snapshot (spec §18) —
application rollback only; it never touches a database or reverses migrations.

Every state change writes an audit record. Production is the default environment,
and the publish action is the human-driven gate (the customer clicks Publish).
"""
from __future__ import annotations

import re

from django.utils import timezone
from django.utils.text import slugify

from apps.audit.service import record as audit
from apps.publishing import readiness as rd
from apps.publishing.hosting import HostError, get_host
from apps.publishing.models import PublishCheck, PublishState, PublishVersion, Website


class PublishError(Exception):
    pass


def get_or_create_website(project, *, subdomain=None) -> Website:
    site = getattr(project, "website", None)
    if site:
        return site
    base = slugify(subdomain or project.slug or project.name)[:50] or "site"
    candidate, n = base, 1
    while Website.objects.filter(subdomain=candidate).exists():
        n += 1
        candidate = f"{base}-{n}"[:63]
    return Website.objects.create(project=project, subdomain=candidate,
                                  site_type=_infer_type(project))


def _infer_type(project) -> str:
    text = (project.description or "").lower()
    for key, pat in [("ecommerce", r"shop|store|e-?commerce|product|cart"),
                     ("blog", r"blog|articles?|posts?"),
                     ("portfolio", r"portfolio"),
                     ("landing", r"landing")]:
        if re.search(pat, text):
            return key
    return "business"


def _next_version(website: Website) -> str:
    last = website.versions.order_by("-created_at").first()
    if not last:
        return "v1.0.0"
    m = re.match(r"v(\d+)\.(\d+)\.(\d+)", last.version)
    if not m:
        return "v1.0.0"
    major, minor, patch = (int(x) for x in m.groups())
    return f"v{major}.{minor}.{patch + 1}"


def evaluate(website: Website) -> list:
    return rd.evaluate(website)


def publish(website: Website, *, user=None, host="devforge_local", environment="production") -> PublishVersion:
    target = get_host(host)
    if target is None:
        raise PublishError(f"Unknown host '{host}'.")

    checks = rd.evaluate(website)
    version = PublishVersion.objects.create(
        website=website, version=_next_version(website), environment=environment,
        host=host, state=PublishState.PUBLISHING, readiness=rd.score(checks),
        created_by=user, commit=_head(website),
    )
    PublishCheck.objects.bulk_create([
        PublishCheck(version=version, key=c.key, label=c.label, status=c.status, detail=c.detail)
        for c in checks
    ])

    if not rd.can_publish(checks):
        version.state = PublishState.FAILED
        version.log = "Nothing to publish — build the site first."
        version.save(update_fields=["state", "log"])
        audit("website.publish_failed", actor=user, organization=website.project.organization,
              target=f"website:{website.id}", summary="no build")
        return version

    try:
        url, log = target.publish(version)
    except HostError as exc:
        version.state = PublishState.FAILED
        version.log = str(exc)
        version.save(update_fields=["state", "log"])
        audit("website.publish_failed", actor=user, organization=website.project.organization,
              target=f"website:{website.id}", summary=str(exc)[:120])
        return version

    from apps.publishing.hosting import published_root
    version.artifact_dir = str(published_root() / website.subdomain / version.version)
    version.url = url
    version.log = log
    version.save(update_fields=["artifact_dir", "url", "log"])

    # Real health check on the served snapshot.
    status, detail = target.health(version)
    version.health, version.health_detail = status, detail
    version.state = PublishState.LIVE if status == "healthy" else PublishState.NEEDS_ATTENTION
    version.save(update_fields=["health", "health_detail", "state"])

    if version.state == PublishState.LIVE:
        website.versions.exclude(pk=version.pk).update(is_current=False)
        version.is_current = True
        version.save(update_fields=["is_current"])

    # Record the first monitoring datapoint for this live version.
    from apps.publishing import monitor
    monitor.run_check(website)
    audit("website.published", actor=user, organization=website.project.organization,
          target=f"website:{website.id}", summary=f"{version.version} · {status}",
          metadata={"url": url})
    return version


def health_check(version: PublishVersion) -> PublishVersion:
    target = get_host(version.host)
    status, detail = target.health(version) if target else ("unknown", "Unknown host")
    version.health, version.health_detail = status, detail
    if version.is_current and status == "down":
        version.state = PublishState.NEEDS_ATTENTION
    version.save(update_fields=["health", "health_detail", "state"])
    # Record a monitoring datapoint too.
    from apps.publishing import monitor
    monitor.run_check(version.website)
    return version


def rollback(website: Website, *, user=None) -> PublishVersion:
    """Re-point the site to the previous LIVE version (spec §18). App-only —
    databases/migrations are never touched here."""
    live = list(website.versions.filter(state__in=[PublishState.LIVE, PublishState.NEEDS_ATTENTION])
                .order_by("-created_at"))
    current = website.current
    target = next((v for v in live if v.pk != (current.pk if current else None)), None)
    if target is None:
        raise PublishError("No previous version to roll back to.")
    website.versions.update(is_current=False)
    target.is_current = True
    target.save(update_fields=["is_current"])
    audit("website.rollback", actor=user, organization=website.project.organization,
          target=f"website:{website.id}", summary=f"→ {target.version}")
    return target


def _head(website: Website) -> str:
    try:
        from apps.repositories.service import repo_for_project
        repo = repo_for_project(website.project)
        return repo.head() if repo.is_initialized else ""
    except Exception:
        return ""
