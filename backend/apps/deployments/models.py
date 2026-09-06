"""Deployment records.

One row per deploy attempt, attributable to a project/workspace/environment and
the provider used. Production deploys carry an approval gate (docs/PRODUCT.md §17,
§27): they cannot run until a human approves — no autonomous production changes.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class DeployEnvironment(models.TextChoices):
    DEVELOPMENT = "development", "Development"
    STAGING = "staging", "Staging"
    PRODUCTION = "production", "Production"


class DeploymentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    WAITING_FOR_APPROVAL = "waiting_for_approval", "Waiting for approval"
    DEPLOYING = "deploying", "Deploying"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class Deployment(models.Model):
    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="deployments"
    )
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deployments",
    )
    environment = models.CharField(max_length=20, choices=DeployEnvironment.choices)
    provider = models.CharField(max_length=64)
    status = models.CharField(
        max_length=32, choices=DeploymentStatus.choices, default=DeploymentStatus.PENDING
    )
    url = models.CharField(max_length=1024, blank=True)
    log = models.TextField(blank=True)

    approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_deployments",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_deployments",
    )
    created_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.project.slug} -> {self.environment} ({self.status})"

    @property
    def is_production(self) -> bool:
        return self.environment == DeployEnvironment.PRODUCTION
