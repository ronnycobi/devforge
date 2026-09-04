"""Workspaces — an isolated working environment inside a Project.

Assumption (recorded per CLAUDE.md): a workspace is where agents actually do
work for a project — it will later own the repository checkout, agent runs, and
builds for one environment. A project starts with a single default "Main"
workspace and may gain more (e.g. staging, production, or parallel feature
contexts) in later phases. Isolation is inherited from the parent project's
organization; there is no cross-project workspace.
"""
from django.db import models
from django.utils import timezone

from apps.core.slugs import unique_slug


class Environment(models.TextChoices):
    DEVELOPMENT = "development", "Development"
    STAGING = "staging", "Staging"
    PRODUCTION = "production", "Production"


class Workspace(models.Model):
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        related_name="workspaces",
    )
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
    environment = models.CharField(
        max_length=20,
        choices=Environment.choices,
        default=Environment.DEVELOPMENT,
    )
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["project", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "slug"],
                name="unique_workspace_slug_per_project",
            ),
            # At most one default workspace per project.
            models.UniqueConstraint(
                fields=["project"],
                condition=models.Q(is_default=True),
                name="one_default_workspace_per_project",
            ),
        ]

    def __str__(self):
        return f"{self.name} · {self.project.name}"

    @property
    def organization(self):
        """Tenant this workspace belongs to (via its project)."""
        return self.project.organization

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(
                Workspace,
                self.name,
                scope={"project": self.project},
                instance=self,
                fallback="workspace",
            )
        super().save(*args, **kwargs)
