"""Change orchestration: plan → estimate → approve → implement.

Implementation reuses the existing specialist agents against the SAME project, so
they read the current context (the twin) and upsert — modifying the application
rather than regenerating it.
"""
from __future__ import annotations

from apps.changes.models import ChangeRequest, ChangeStatus
from apps.changes.planner import plan_change
from apps.costs.estimator import estimate_project
from apps.database import migration_service
from apps.database.migration_planner import plan_migration_sql
from apps.orchestrator.models import AgentTask, TaskStatus
from apps.orchestrator.service import Orchestrator
from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.repositories.service import repo_for_project
from apps.technology.registry import technology_for_role

# Which specialist implements each affected area (api folds into backend).
_AREA_AGENTS = {
    "database": "database",
    "backend": "backend",
    "api": "backend",
    "frontend": "frontend",
    "testing": "testing",
}
# Order changes are applied in; review always runs last.
_ORDER = ["database", "backend", "frontend", "testing"]

_TWIN_KINDS = [
    ContextKind.REQUIREMENT, ContextKind.ARCHITECTURE, ContextKind.TECH_DECISION,
    ContextKind.API, ContextKind.SCHEMA, ContextKind.SCREEN,
]


def create_change(project, description, created_by):
    return ChangeRequest.objects.create(
        project=project, description=description.strip(), created_by=created_by
    )


def build_plan(change: ChangeRequest, router=None) -> ChangeRequest:
    """Analyze the twin, produce an impact plan + estimate, set the approval gate.

    When the change touches the database, also plan a first-class DatabaseMigration
    (risk-classified) — a destructive migration forces the whole change to require
    approval, so schema risk surfaces at the change gate.
    """
    twin = ProjectContext(change.project).digest(kinds=_TWIN_KINDS, max_chars=4000)
    plan = plan_change(change.description, twin, router=router)
    change.plan = plan
    change.requires_approval = plan.get("requires_approval", True)
    change.estimate = _estimate(plan)

    _plan_migration(change, twin, router)  # may set change.migration + raise the gate

    change.status = (
        ChangeStatus.AWAITING_APPROVAL if change.requires_approval else ChangeStatus.PLANNED
    )
    change.save()
    return change


def _plan_migration(change: ChangeRequest, twin_digest: str, router) -> None:
    """If the plan touches the database, plan + record a migration for it."""
    if not (change.plan.get("affected_areas", {}) or {}).get("database"):
        return
    db_tech = technology_for_role(change.project, "database")
    if db_tech is None:
        return  # unknown datastore → no SQL migration can be planned safely
    spec = plan_migration_sql(change.description, twin_digest, db_tech.id, router=router)
    if not spec:
        return  # offline / non-migration engine → nothing planned (honest)
    try:
        mig = migration_service.plan_migration(
            change.project, db_tech.id,
            description=spec["description"] or change.description[:200],
            operation=spec["operation"], up_sql=spec["up_sql"],
            down_sql=spec["down_sql"], created_by=change.created_by,
        )
    except migration_service.MigrationError:
        return  # engine can't do migrations → skip, don't fake
    change.migration = mig
    if mig.requires_approval:
        change.requires_approval = True


def _implementing_agents(plan: dict) -> list[str]:
    areas = plan.get("affected_areas", {})
    agents, seen = [], set()
    for area in _ORDER:
        if areas.get(area):
            key = _AREA_AGENTS[area]
            if key not in seen:
                agents.append(key)
                seen.add(key)
    # 'api' maps to backend too.
    if areas.get("api") and "backend" not in seen:
        agents.insert(0, "backend")
    if agents:
        agents.append("code_review")
        agents.append("security")  # deterministic static scan, always last
    return agents


def _estimate(plan: dict) -> dict:
    agents = _implementing_agents(plan)
    if not agents:
        return {"credits": [0, 0], "cost_usd": [0, 0], "agents": [], "risk": plan.get("risk")}
    est = estimate_project(agents)
    return {
        "credits": est["credits"], "cost_usd": est["cost_usd"],
        "agents": agents, "risk": plan.get("risk"),
    }


def approve(change: ChangeRequest, user) -> ChangeRequest:
    change.approved = True
    change.approved_by = user
    if change.status == ChangeStatus.AWAITING_APPROVAL:
        change.status = ChangeStatus.PLANNED
    change.save(update_fields=["approved", "approved_by", "status", "updated_at"])
    # Approving the change approves its migration too, so it's ready to apply at
    # deploy (DevForge doesn't apply to a customer DB it has no connection to).
    if change.migration_id and not change.migration.approved:
        migration_service.approve(change.migration, user)
    from apps.audit.service import record
    record("change.approved", actor=user, organization=change.project.organization,
           target=f"change:{change.id}", summary=change.description[:200])
    return change


def implement(change: ChangeRequest) -> ChangeRequest:
    if change.requires_approval and not change.approved:
        return change  # still gated
    agents = _implementing_agents(change.plan)
    if not agents:
        # Nothing actionable was planned (e.g. offline stub) — honest no-op.
        change.status = ChangeStatus.DONE
        change.save(update_fields=["status", "updated_at"])
        return change

    orch = Orchestrator()
    brief = f"Change request: {change.description}"
    previous = None
    ids = []
    for key in agents:
        task = orch.create_task(
            project=change.project, agent_key=key,
            input={"brief": brief}, created_by=change.created_by,
        )
        if previous is not None:
            task.depends_on.set([previous])
        previous = task
        ids.append(task.id)

    repo = repo_for_project(change.project)
    change.base_commit = repo.head() if repo.is_initialized else ""
    change.task_ids = ids
    change.status = ChangeStatus.IMPLEMENTING
    change.save(update_fields=["base_commit", "task_ids", "status", "updated_at"])

    orch.run_ready(change.project)

    # Report the real outcome: DONE only if every task actually completed;
    # FAILED (with which agents failed) otherwise. Never claim success blindly.
    change.result = _summarize_tasks(ids)
    change.result_commit = repo.head() if repo.is_initialized else ""
    change.status = ChangeStatus.DONE if change.result["ok"] else ChangeStatus.FAILED
    change.save(update_fields=["result", "result_commit", "status", "updated_at"])
    from apps.audit.service import record
    record(
        "change.implemented" if change.result["ok"] else "change.failed",
        actor=change.created_by, organization=change.project.organization,
        target=f"change:{change.id}",
        summary=f"{change.result['completed']}/{change.result['total']} steps",
        metadata={"commit": change.result_commit, "failed": change.result.get("failed", [])},
    )
    return change


def rollback(change: ChangeRequest) -> ChangeRequest:
    """Reverse an implemented change by restoring the repo to its base commit."""
    if not change.can_rollback:
        return change
    repo = repo_for_project(change.project)
    repo.reset_hard(change.base_commit)
    change.status = ChangeStatus.ROLLED_BACK
    change.save(update_fields=["status", "updated_at"])
    return change


def change_diff(change: ChangeRequest) -> str:
    """The code diff this change introduced (base → result), if any."""
    if not (change.base_commit and change.result_commit):
        return ""
    return repo_for_project(change.project).diff_between(
        change.base_commit, change.result_commit
    )


def _summarize_tasks(task_ids: list[int]) -> dict:
    tasks = {t.id: t for t in AgentTask.objects.filter(id__in=task_ids)}
    ordered = [tasks[i] for i in task_ids if i in tasks]
    agents = [
        {
            "agent": t.agent_key,
            "status": t.status,
            "ok": t.status == TaskStatus.COMPLETED,
            "files": (t.output or {}).get("files_generated", 0),
            "verified": (t.output or {}).get("verified"),
            "tests_passed": (t.output or {}).get("tests_passed"),
            "error": t.error or "",
        }
        for t in ordered
    ]
    failed = [a["agent"] for a in agents if not a["ok"]]
    return {
        "ok": not failed and bool(agents),
        "agents": agents,
        "failed": failed,
        "completed": sum(1 for a in agents if a["ok"]),
        "total": len(agents),
    }
