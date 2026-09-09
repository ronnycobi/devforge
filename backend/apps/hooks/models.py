"""Generation hooks — first-class guardrails on the build → deploy pipeline.

A Hook fires at a pipeline EVENT (pre_deploy, post_build, …) and runs an ACTION
(run the tests, run the security scan, a manual gate). A *blocking* hook that fails
stops promotion; a non-blocking one just records a HookRun. Actions reuse DevForge's
existing machinery (the test runner, the security scanner) — they orchestrate, they
don't reinvent.
"""
from __future__ import annotations

from django.db import models
from django.utils import timezone


class HookEvent(models.TextChoices):
    PRE_CHANGE = "pre_change", "Before a change"
    POST_BUILD = "post_build", "After a build"
    PRE_DEPLOY = "pre_deploy", "Before deploy"
    POST_DEPLOY = "post_deploy", "After deploy"


class Hook(models.Model):
    ACTIONS = [("run_tests", "Run tests"), ("security_scan", "Security scan"),
               ("manual_gate", "Manual sign-off gate")]
    SCOPE_GLOBAL, SCOPE_ORG, SCOPE_PROJECT = "global", "org", "project"

    name = models.CharField(max_length=120)
    event = models.CharField(max_length=16, choices=HookEvent.choices)
    action = models.CharField(max_length=24)
    blocking = models.BooleanField(default=True)   # a failing blocking hook stops promotion
    scope = models.CharField(max_length=8, default=SCOPE_GLOBAL)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, null=True, blank=True,
        related_name="hooks",
    )
    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, null=True, blank=True, related_name="hooks"
    )
    config = models.JSONField(default=dict, blank=True)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["event", "name"]

    def __str__(self):
        return f"{self.name} @ {self.event} ({'blocking' if self.blocking else 'advisory'})"


class HookRun(models.Model):
    hook = models.ForeignKey(Hook, on_delete=models.CASCADE, related_name="runs")
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="hook_runs")
    event = models.CharField(max_length=16)
    status = models.CharField(max_length=8)   # pass / fail / skip
    blocked = models.BooleanField(default=False)
    detail = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.hook.name}: {self.status}"
