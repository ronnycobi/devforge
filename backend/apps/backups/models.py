"""Project backups — named restore points over the project repository.

A backup captures the repo's current commit; restoring resets the working tree
back to it. Simple, real, and reversible — a customer can snapshot before a big
change and roll back if they don't like the result.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class ProjectBackup(models.Model):
    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="backups"
    )
    label = models.CharField(max_length=200)
    commit_sha = models.CharField(max_length=40)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="created_backups",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.label} @ {self.commit_sha} ({self.project})"
