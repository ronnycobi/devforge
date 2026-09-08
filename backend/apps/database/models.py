"""Database migrations as first-class, tracked objects (Database charter §11).

A DatabaseMigration records one schema/data change for a project's database: what
it does, how to undo it, its risk, whether it needs approval, and — once run —
whether it applied. It is engine-agnostic (the SQL/ops are the caller's; the
provider runs them) and safety-gated: destructive operations require explicit
approval before they can be applied. This is the customer-project migration
record; it is unrelated to DevForge's own Django migrations.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class MigrationOp(models.TextChoices):
    CREATE = "create", "Create"
    ALTER = "alter", "Alter"
    DROP = "drop", "Drop"
    RENAME = "rename", "Rename"
    INDEX = "index", "Index"
    CONSTRAINT = "constraint", "Constraint"
    DATA = "data", "Data migration"


class MigrationStatus(models.TextChoices):
    PLANNED = "planned", "Planned"
    AWAITING_APPROVAL = "awaiting_approval", "Awaiting approval"
    APPROVED = "approved", "Approved"
    APPLIED = "applied", "Applied"
    ROLLED_BACK = "rolled_back", "Rolled back"
    FAILED = "failed", "Failed"


class RiskLevel(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"


class DatabaseMigration(models.Model):
    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="db_migrations"
    )
    database_id = models.CharField(max_length=64)  # capability-registry id
    version = models.CharField(max_length=64)
    description = models.CharField(max_length=500)
    operation = models.CharField(max_length=20, choices=MigrationOp.choices)

    up_sql = models.TextField()
    down_sql = models.TextField(blank=True)  # rollback strategy ("" = irreversible)

    status = models.CharField(
        max_length=24, choices=MigrationStatus.choices, default=MigrationStatus.PLANNED
    )
    risk_level = models.CharField(
        max_length=10, choices=RiskLevel.choices, default=RiskLevel.LOW
    )
    requires_approval = models.BooleanField(default=False)

    depends_on = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="dependents"
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="created_db_migrations",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="approved_db_migrations",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now)
    applied_at = models.DateTimeField(null=True, blank=True)
    execution_ms = models.PositiveIntegerField(null=True, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["project_id", "version"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "version"], name="uniq_migration_version_per_project"
            )
        ]

    def __str__(self):
        return f"{self.version} {self.description} ({self.status})"

    @property
    def reversible(self) -> bool:
        return bool(self.down_sql.strip())

    @property
    def approved(self) -> bool:
        return self.approved_by_id is not None
