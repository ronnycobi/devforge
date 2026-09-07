"""Project intelligence — durable, structured per-project knowledge.

Each ContextEntry is one fact about a project (a requirement, a technical
decision, a schema note, a known issue, an agent decision, …). Agents read a
compact digest of this instead of re-reading the whole repository each time,
which is what keeps long-running projects cheap and consistent (docs/PRODUCT.md
§3). Everything is scoped to a Project and, through it, to the tenant.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class ContextKind(models.TextChoices):
    REQUIREMENT = "requirement", "Requirement"
    ARCHITECTURE = "architecture", "Architecture"
    BUSINESS_RULE = "business_rule", "Business rule"
    TECH_DECISION = "tech_decision", "Technical decision"
    STACK = "stack", "Stack proposal"
    SCHEMA = "schema", "Database schema"
    API = "api", "API"
    SCREEN = "screen", "Screen / UI"
    DEPENDENCY = "dependency", "Dependency"
    KNOWN_ISSUE = "known_issue", "Known issue"
    REVIEW = "review", "Review finding"
    AGENT_DECISION = "agent_decision", "Agent decision"
    DEPLOYMENT = "deployment", "Deployment"
    INFRASTRUCTURE = "infrastructure", "Infrastructure"
    TESTING = "testing", "Testing"
    SECURITY = "security", "Security"
    NOTE = "note", "Note"


class ContextEntry(models.Model):
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        related_name="context_entries",
    )
    kind = models.CharField(max_length=32, choices=ContextKind.choices)
    key = models.SlugField(max_length=255)
    title = models.CharField(max_length=255)
    content = models.TextField(blank=True)
    data = models.JSONField(default=dict, blank=True)
    # Free-form provenance, e.g. "user", "agent:architect", "agent:backend#task:12".
    source = models.CharField(max_length=255, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="context_entries",
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["kind", "key"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "kind", "key"],
                name="unique_context_entry_per_project_kind",
            )
        ]
        indexes = [models.Index(fields=["project", "kind"])]

    def __str__(self):
        return f"{self.kind}:{self.key} ({self.project.slug})"
