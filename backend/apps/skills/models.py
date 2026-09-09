"""Skills library — reusable playbooks the build flow injects as guidance.

A Skill is saved instructions ("how to build X") that the orchestrator selects when a
brief matches its trigger keywords, then feeds to the agents. Generalizes one-off
triggers like store provisioning into an authorable mechanism.

Scope: a global skill applies to everyone; an org- or project-scoped skill lets a
customer encode "how we build things here" without affecting other tenants.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class Skill(models.Model):
    SCOPE_GLOBAL = "global"
    SCOPE_ORG = "org"
    SCOPE_PROJECT = "project"

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=64)
    description = models.CharField(max_length=255, blank=True)
    keywords = models.JSONField(default=list, blank=True)   # ["shop","store",…]
    body = models.TextField()                               # the guidance itself
    scope = models.CharField(max_length=8, default=SCOPE_GLOBAL)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, null=True, blank=True,
        related_name="skills",
    )
    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, null=True, blank=True, related_name="skills"
    )
    enabled = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="authored_skills",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.scope})"

    def matches(self, text: str) -> bool:
        low = (text or "").lower()
        return any(kw.lower() in low for kw in (self.keywords or []))
