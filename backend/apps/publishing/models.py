"""Website Creation & Publishing — data model (spec §5, §17, §41, §42).

Phase 1 (spec §51): a project's website facet, versioned publishes, a working
DevForge URL, health, and rollback. Reuses existing DevForge infrastructure
(Project/Organization/Repository/Audit) rather than duplicating it (spec §1).

HONESTY (spec §50): a PublishVersion is only LIVE when its build was actually
snapshotted and is served by DevForge. Public custom-domain + SSL hosting needs
cloud/DNS infra that isn't configured here; that stays a Phase-2 gated path and is
never shown as active until it is.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class PublishState(models.TextChoices):
    # Customer-facing states (spec §42) — no internal agent topology.
    DRAFT = "draft", "Draft"
    BUILDING = "building", "Building"
    TESTING = "testing", "Testing"
    READY = "ready", "Ready to publish"
    PUBLISHING = "publishing", "Publishing"
    LIVE = "live", "Live"
    NEEDS_ATTENTION = "needs_attention", "Needs attention"
    FAILED = "failed", "Failed"


class Website(models.Model):
    """A project's published-website facet (spec §5 Digital Twin surface)."""

    project = models.OneToOneField(
        "projects.Project", on_delete=models.CASCADE, related_name="website"
    )
    subdomain = models.SlugField(max_length=63, unique=True)
    site_type = models.CharField(max_length=32, default="business")   # inferred; not forced
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.subdomain} ({self.project.name})"

    @property
    def current(self):
        return self.versions.filter(is_current=True).first()


class PublishVersion(models.Model):
    """One versioned publish of a website to an environment (spec §17)."""

    website = models.ForeignKey(Website, on_delete=models.CASCADE, related_name="versions")
    version = models.CharField(max_length=32)                 # v1.0.0, v1.0.1, …
    environment = models.CharField(max_length=20, default="production")
    host = models.CharField(max_length=32, default="devforge_local")
    state = models.CharField(max_length=20, choices=PublishState.choices, default=PublishState.DRAFT)
    url = models.CharField(max_length=1024, blank=True)       # working DevForge URL when live
    artifact_dir = models.CharField(max_length=1024, blank=True)  # snapshot served for this version
    commit = models.CharField(max_length=40, blank=True)
    health = models.CharField(max_length=16, default="unknown")   # unknown / healthy / down
    health_detail = models.CharField(max_length=255, blank=True)
    readiness = models.PositiveSmallIntegerField(default=0)
    is_current = models.BooleanField(default=False)
    log = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="publish_versions",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.website.subdomain} {self.version} ({self.state})"


class PublishCheck(models.Model):
    """One publish-readiness check result (spec §12, §41)."""

    version = models.ForeignKey(PublishVersion, on_delete=models.CASCADE, related_name="checks")
    key = models.CharField(max_length=32)
    label = models.CharField(max_length=128)
    status = models.CharField(max_length=16)     # ok / warn / fail / manual
    detail = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.key}={self.status}"
