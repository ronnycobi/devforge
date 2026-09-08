"""Change requests — DevForge as a continuous engineering partner.

A customer describes a change in natural language ("add PayFast payments", "the
checkout isn't working", "add multi-company support"). DevForge reads the project's
Software Digital Twin (its accumulated context), produces an impact plan and a
cost estimate, gates significant changes on approval, then implements them by
orchestrating the specialist agents against the EXISTING project — modifying the
twin rather than regenerating from scratch.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class ChangeStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PLANNED = "planned", "Planned"
    AWAITING_APPROVAL = "awaiting_approval", "Awaiting approval"
    IMPLEMENTING = "implementing", "Implementing"
    DONE = "done", "Done"
    FAILED = "failed", "Failed"


class ChangeRequest(models.Model):
    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="changes"
    )
    description = models.TextField()
    status = models.CharField(
        max_length=32, choices=ChangeStatus.choices, default=ChangeStatus.DRAFT
    )
    plan = models.JSONField(default=dict, blank=True)      # {summary, affected_areas, steps, risk}
    estimate = models.JSONField(default=dict, blank=True)  # {credits:[lo,hi], cost_usd:[lo,hi], ...}
    requires_approval = models.BooleanField(default=False)
    approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="approved_changes",
    )
    task_ids = models.JSONField(default=list, blank=True)  # AgentTask ids created to implement it
    # First-class DB migration this change plans (when it touches the schema).
    migration = models.ForeignKey(
        "database_agent.DatabaseMigration", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="change_requests",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="created_changes",
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Change #{self.pk}: {self.description[:50]}"

    @property
    def risk(self) -> str:
        return (self.plan or {}).get("risk", "medium")
