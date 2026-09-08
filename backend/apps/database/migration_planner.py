"""Plan a concrete database migration for a requested change.

Given the existing schema (from the twin) and a change description, ask the model
for ONE migration as SQL (up + down) in the project database's dialect. This is
what lets a change-request produce a first-class, risk-classified, approval-gated
DatabaseMigration rather than only regenerating ORM models. Offline (stub) yields
nothing — no fabricated SQL. Engines without migrations return nothing too.
"""
from __future__ import annotations

from apps.ai_providers.base import Message
from apps.core.jsonx import extract_json
from apps.database.capabilities import get_database
from apps.database.models import MigrationOp
from apps.model_router.router import ModelRouter, RoutingRequest, TaskComplexity


def _system_prompt(dialect: str) -> str:
    return (
        "You are DevForge's database migration planner. Given an existing schema "
        "and a requested change, produce exactly ONE migration for the change — "
        "not a rewrite of the schema.\n\n"
        f"Target SQL dialect: {dialect}.\n"
        "Respond with ONLY a JSON object:\n"
        '  "operation": one of create, alter, drop, rename, index, constraint, data,\n'
        '  "description": a short summary of the migration,\n'
        '  "up_sql": the SQL that applies the change,\n'
        '  "down_sql": the SQL that reverses it ("" if truly irreversible).\n'
        "Prefer backward-compatible, additive changes. No prose outside the JSON."
    )


def _clean(payload) -> dict | None:
    if not isinstance(payload, dict):
        return None
    up_sql = str(payload.get("up_sql") or "").strip()
    if not up_sql:
        return None
    operation = str(payload.get("operation") or "").strip().lower()
    if operation not in MigrationOp.values:
        operation = MigrationOp.ALTER  # safe, capability-neutral default
    return {
        "operation": operation,
        "description": str(payload.get("description") or "").strip(),
        "up_sql": up_sql,
        "down_sql": str(payload.get("down_sql") or "").strip(),
    }


def plan_migration_sql(description, schema_digest, database_id, router=None) -> dict | None:
    """Return {operation, description, up_sql, down_sql} for the change, or None."""
    profile = get_database(database_id)
    if profile is None or not profile.supports("migrations"):
        return None  # no SQL migration concept for this engine
    router = router or ModelRouter()
    user = (
        (f"Existing schema:\n{schema_digest}\n\n" if (schema_digest or "").strip() else "")
        + f"Requested change:\n{description}\n\nReturn the migration JSON."
    )
    response = router.complete(
        RoutingRequest(complexity=TaskComplexity.HIGH, task_type="migration_plan"),
        messages=[Message("user", user)],
        system=_system_prompt(profile.name),
        max_tokens=1500,
    )
    return _clean(extract_json(response.text))
