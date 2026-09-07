"""Change orchestration: plan → estimate → approve → implement.

Implementation reuses the existing specialist agents against the SAME project, so
they read the current context (the twin) and upsert — modifying the application
rather than regenerating it.
"""
from __future__ import annotations

from apps.changes.models import ChangeRequest, ChangeStatus
from apps.changes.planner import plan_change
from apps.costs.estimator import estimate_project
from apps.orchestrator.service import Orchestrator
from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext

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
    """Analyze the twin, produce an impact plan + estimate, set the approval gate."""
    twin = ProjectContext(change.project).digest(kinds=_TWIN_KINDS, max_chars=4000)
    plan = plan_change(change.description, twin, router=router)
    change.plan = plan
    change.requires_approval = plan.get("requires_approval", True)
    change.estimate = _estimate(plan)
    change.status = (
        ChangeStatus.AWAITING_APPROVAL if change.requires_approval else ChangeStatus.PLANNED
    )
    change.save()
    return change


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

    change.task_ids = ids
    change.status = ChangeStatus.IMPLEMENTING
    change.save(update_fields=["task_ids", "status", "updated_at"])

    orch.run_ready(change.project)

    change.status = ChangeStatus.DONE
    change.save(update_fields=["status", "updated_at"])
    return change
