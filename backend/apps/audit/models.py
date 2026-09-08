"""Audit log — an append-only record of security-relevant actions.

Who did what, to what, when: approvals, implementations, migrations, deploys, and
membership changes. Recorded best-effort (auditing never breaks the action) and
scoped to an organization so it can be shown per-tenant or platform-wide.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class AuditEvent(models.Model):
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    action = models.CharField(max_length=64)          # e.g. "change.approved"
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="audit_events",
    )
    organization = models.ForeignKey(
        "organizations.Organization", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="audit_events",
    )
    target = models.CharField(max_length=128, blank=True)   # e.g. "change:12"
    summary = models.CharField(max_length=500, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["organization", "-created_at"])]

    def __str__(self):
        who = self.actor_id and self.actor.email or "system"
        return f"{self.action} by {who} ({self.target})"
