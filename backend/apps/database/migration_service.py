"""Plan, classify, approve, apply and roll back database migrations.

Migrations are engine-agnostic records; a DatabaseProvider actually runs the SQL.
Safety is enforced here (charter §10/§11): destructive operations are classified
HIGH risk and require explicit approval before they can be applied, and a
migration can only be planned for a database whose capabilities include
migrations (a key-value or schema-less store is rejected honestly).
"""
from __future__ import annotations

import re
import time

from django.utils import timezone

from apps.database.capabilities import get_database
from apps.database.models import (
    DatabaseMigration,
    MigrationOp,
    MigrationStatus,
    RiskLevel,
)

# SQL that can destroy or lose data / break compatibility → HIGH + approval.
_DESTRUCTIVE = [
    r"\bdrop\s+table\b",
    r"\bdrop\s+column\b",
    r"\bdrop\s+constraint\b",
    r"\bdelete\s+from\b",
    r"\btruncate\b",
    r"\balter\s+column\b.*\btype\b",   # PostgreSQL type change
    r"\bmodify\s+column\b",            # MySQL type change
    r"\bdrop\s+not\s+null\b|\bset\s+not\s+null\b",
]


class MigrationError(Exception):
    pass


def classify(up_sql: str, operation: str) -> tuple[str, bool]:
    """Return (risk_level, requires_approval) for a migration's SQL + operation."""
    text = (up_sql or "").lower()
    if operation == MigrationOp.DROP or any(re.search(p, text) for p in _DESTRUCTIVE):
        return RiskLevel.HIGH, True
    if operation == MigrationOp.DATA:
        return RiskLevel.MEDIUM, True  # touching data warrants a human check
    if operation in (MigrationOp.ALTER, MigrationOp.RENAME, MigrationOp.CONSTRAINT):
        return RiskLevel.MEDIUM, False
    return RiskLevel.LOW, False  # CREATE / INDEX


def plan_migration(
    project, database_id, *, description, operation, up_sql,
    down_sql="", created_by=None, version=None, depends_on=None,
) -> DatabaseMigration:
    """Create a tracked migration, refusing engines that don't do migrations."""
    profile = get_database(database_id)
    if profile is None:
        raise MigrationError(f"Unknown database '{database_id}'.")
    if not profile.supports("migrations"):
        raise MigrationError(
            f"{profile.name} ({profile.category.value}) does not use schema "
            "migrations — model it on its own terms."
        )
    if operation not in MigrationOp.values:
        raise MigrationError(f"Unknown operation '{operation}'.")

    risk, requires_approval = classify(up_sql, operation)
    version = version or timezone.now().strftime("%Y%m%d%H%M%S%f")
    status = MigrationStatus.AWAITING_APPROVAL if requires_approval else MigrationStatus.PLANNED
    return DatabaseMigration.objects.create(
        project=project, database_id=database_id, version=version,
        description=description, operation=operation, up_sql=up_sql, down_sql=down_sql,
        status=status, risk_level=risk, requires_approval=requires_approval,
        created_by=created_by, depends_on=depends_on,
    )


def approve(migration: DatabaseMigration, user) -> DatabaseMigration:
    migration.approved_by = user
    migration.approved_at = timezone.now()
    if migration.status == MigrationStatus.AWAITING_APPROVAL:
        migration.status = MigrationStatus.APPROVED
    migration.save(update_fields=["approved_by", "approved_at", "status"])
    return migration


def apply(migration: DatabaseMigration, provider) -> DatabaseMigration:
    """Run the migration's up_sql through a provider. Blocks on unapproved risk."""
    if migration.status == MigrationStatus.APPLIED:
        return migration
    if migration.requires_approval and not migration.approved:
        raise MigrationError(
            f"Migration {migration.version} is {migration.risk_level} risk and "
            "requires approval before it can be applied."
        )
    if migration.depends_on and migration.depends_on.status != MigrationStatus.APPLIED:
        raise MigrationError(
            f"Migration {migration.version} depends on {migration.depends_on.version}, "
            "which is not applied."
        )
    start = time.monotonic()
    try:
        provider.execute_query(migration.up_sql)
    except Exception as exc:  # provider/driver error → recorded, not hidden
        migration.status = MigrationStatus.FAILED
        migration.error = str(exc)[:2000]
        migration.save(update_fields=["status", "error"])
        raise MigrationError(f"Migration failed: {exc}") from exc
    migration.status = MigrationStatus.APPLIED
    migration.applied_at = timezone.now()
    migration.execution_ms = int((time.monotonic() - start) * 1000)
    migration.error = ""
    migration.save(update_fields=["status", "applied_at", "execution_ms", "error"])
    return migration


def rollback(migration: DatabaseMigration, provider) -> DatabaseMigration:
    """Run the migration's down_sql to reverse it."""
    if not migration.reversible:
        raise MigrationError(f"Migration {migration.version} has no rollback strategy.")
    try:
        provider.execute_query(migration.down_sql)
    except Exception as exc:
        migration.status = MigrationStatus.FAILED
        migration.error = str(exc)[:2000]
        migration.save(update_fields=["status", "error"])
        raise MigrationError(f"Rollback failed: {exc}") from exc
    migration.status = MigrationStatus.ROLLED_BACK
    migration.save(update_fields=["status"])
    return migration
