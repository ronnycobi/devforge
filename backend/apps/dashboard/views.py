"""Server-rendered Django UI for DevForge (the customer control plane).

Session-authenticated, tenant-scoped through org membership. Dark developer-
platform experience. This is DevForge's own operator UI — distinct from the
software DevForge generates for customers. UI layer only: it reads the same
models/services as the API and never bypasses tenant scoping.

Pages backed by real data are implemented; areas without a backend yet render an
honest "coming soon" shell rather than fabricated metrics.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.agents.definitions import registry as agent_registry
from apps.changes import service as changes_service
from apps.changes.models import ChangeRequest
from apps.credits.models import CreditAccount, UsageRecord
from apps.credits.services import plans
from apps.deployments.models import Deployment, DeploymentStatus
from apps.organizations.access import (
    manageable_organizations_for,
    organizations_for,
)
from apps.organizations.models import Organization
from apps.orchestrator.models import TERMINAL_STATUSES, AgentTask
from apps.orchestrator.service import Orchestrator
from apps.project_context.models import ContextEntry, ContextKind
from apps.projects.models import Project
from apps.technology.registry import ROLES
from apps.technology.registry import registry as tech_registry

_PIPELINE = [
    ContextKind.REQUIREMENT,
    ContextKind.ARCHITECTURE,
    ContextKind.TECH_DECISION,
    ContextKind.API,
    ContextKind.SCHEMA,
    ContextKind.SCREEN,
    ContextKind.TESTING,
    ContextKind.REVIEW,
]
_NON_TERMINAL = [s for s, _ in AgentTask._meta.get_field("status").choices
                 if s not in TERMINAL_STATUSES]


def _manageable_ids(user):
    return set(manageable_organizations_for(user).values_list("id", flat=True))


def _project_progress(project) -> int:
    """Rough build progress: share of the design pipeline that has content."""
    kinds = set(
        ContextEntry.objects.filter(project=project).values_list("kind", flat=True)
    )
    done = sum(1 for k in _PIPELINE if k in kinds)
    return round(done / len(_PIPELINE) * 100)


def _project_state(project) -> str:
    if project.deployments.filter(status=DeploymentStatus.SUCCEEDED).exists():
        return "Deployed"
    if project.agent_tasks.filter(status__in=_NON_TERMINAL).exists():
        return "Building"
    if project.mode == "import":
        return "Analyzing"
    return project.get_status_display()


# --- overview ---------------------------------------------------------------

@login_required
def overview(request):
    user = request.user
    orgs = list(organizations_for(user))
    projects = list(
        Project.objects.filter(organization__in=orgs).select_related("organization")
    )
    tasks = AgentTask.objects.filter(project__in=projects)

    running = sum(1 for p in projects if p.agent_tasks.filter(status__in=_NON_TERMINAL).exists())
    deployments = Deployment.objects.filter(
        project__in=projects, status=DeploymentStatus.SUCCEEDED
    ).count()

    month_start = date.today().replace(day=1)
    usage = UsageRecord.objects.filter(organization__in=orgs, created_at__date__gte=month_start)
    spend = sum((u.cost_usd for u in usage), Decimal("0"))
    credits_used = sum((u.credits_charged for u in usage), Decimal("0"))
    accounts = CreditAccount.objects.filter(organization__in=orgs)
    allowance = sum(Decimal(plans().get(a.plan, 0)) for a in accounts)
    usage_pct = int(min(credits_used / allowance * 100, 100)) if allowance else None

    active = sorted(projects, key=lambda p: p.updated_at, reverse=True)[:6]
    active_rows = [
        {"project": p, "state": _project_state(p), "progress": _project_progress(p)}
        for p in active
    ]
    activity = [
        {
            "agent": agent_registry.get(t.agent_key).name if t.agent_key in agent_registry else t.agent_key,
            "action": (t.messages[-1] if t.messages else t.get_status_display()),
            "when": t.started_at or t.created_at,
            "status": t.status,
            "project": t.project,
        }
        for t in tasks.select_related("project").order_by("-created_at")[:8]
    ]
    return render(request, "dashboard/overview.html", {
        "active": "overview",
        "greeting_name": (user.short_name or user.email.split("@")[0]),
        "stats": {
            "projects": len(projects), "running": running,
            "deployments": deployments, "incidents": 0,
        },
        "usage_pct": usage_pct, "spend": spend,
        "active_rows": active_rows, "activity": activity,
    })


# --- projects ---------------------------------------------------------------

@login_required
def projects(request):
    orgs = list(organizations_for(request.user))
    manageable = _manageable_ids(request.user)
    if request.method == "POST" and request.POST.get("action") == "create_project":
        org = get_object_or_404(Organization, pk=request.POST.get("organization", 0))
        name = (request.POST.get("name") or "").strip()
        if org.id in manageable and name:
            p = Project.objects.create(organization=org, name=name, created_by=request.user)
            p.ensure_default_workspace()
            messages.success(request, f"Created project “{p.name}”.")
            return redirect("dashboard:project", pk=p.id)
        messages.error(request, "Need a name and owner/admin rights in that org.")
        return redirect("dashboard:projects")

    rows = [
        {"project": p, "state": _project_state(p), "progress": _project_progress(p)}
        for p in Project.objects.filter(organization__in=orgs).select_related("organization")
    ]
    return render(request, "dashboard/projects.html", {
        "active": "projects", "rows": rows,
        "manageable_orgs": [o for o in orgs if o.id in manageable],
    })


@login_required
def project(request, pk):
    proj = get_object_or_404(
        Project.objects.filter(organization__in=organizations_for(request.user)), pk=pk
    )
    can_manage = proj.organization_id in _manageable_ids(request.user)
    if request.method == "POST":
        if not can_manage:
            messages.error(request, "Owner or admin required for this action.")
            return redirect("dashboard:project", pk=pk)
        if request.POST.get("action") == "create_change":
            desc = (request.POST.get("description") or "").strip()
            if desc:
                change = changes_service.create_change(proj, desc, request.user)
                changes_service.build_plan(change)
                return redirect("dashboard:change", pk=change.id)
            messages.error(request, "Describe the change you want.")
            return redirect("dashboard:project", pk=pk)
        _handle_project_action(request, proj)
        return redirect("dashboard:project", pk=pk)

    entries = ContextEntry.objects.filter(project=proj)
    pipeline = [
        {"kind": k, "label": ContextKind(k).label, "entries": [e for e in entries if e.kind == k]}
        for k in _PIPELINE
    ]
    stack_roles = [
        {"role": r, "chosen": (proj.technology or {}).get(r), "options": tech_registry.options_for_role(r)}
        for r in ROLES
    ]
    twin = {
        "components": sum(1 for e in entries if e.kind == ContextKind.ARCHITECTURE),
        "apis": sum(1 for e in entries if e.kind == ContextKind.API),
        "models": sum(1 for e in entries if e.kind == ContextKind.SCHEMA),
        "screens": sum(1 for e in entries if e.kind == ContextKind.SCREEN),
    }
    return render(request, "dashboard/project.html", {
        "active": "projects", "project": proj, "can_manage": can_manage,
        "state": _project_state(proj), "progress": _project_progress(proj),
        "pipeline": pipeline, "tasks": proj.agent_tasks.all(),
        "agents": agent_registry.all(), "stack_roles": stack_roles,
        "twin": twin, "changes": proj.changes.all()[:8],
    })


@login_required
def import_software(request):
    """Import an existing codebase (ZIP upload or Git connect) and analyze it."""
    from apps.ingest.analyzer import IngestError, extract_zip, import_codebase
    from apps.ingest.connect import PROVIDERS, fetch_repo_archive, parse_repo

    orgs = list(organizations_for(request.user))
    manageable = [o for o in orgs if o.id in _manageable_ids(request.user)]

    if request.method == "POST":
        org = get_object_or_404(Organization, pk=request.POST.get("organization", 0))
        name = (request.POST.get("name") or "").strip()
        source = request.POST.get("source") or "zip"
        if org.id not in {o.id for o in manageable} or not name:
            messages.error(request, "Need a name and owner/admin rights in that org.")
            return redirect("dashboard:import")

        # Resolve the chosen source into an in-memory archive.
        try:
            if source == "git":
                provider = request.POST.get("provider") or "github"
                owner, repo = parse_repo(request.POST.get("repo", ""))
                archive = fetch_repo_archive(
                    provider, owner, repo,
                    ref=(request.POST.get("ref") or "").strip(),
                    token=(request.POST.get("token") or "").strip(),
                )
            else:
                upload = request.FILES.get("archive")
                if not upload:
                    messages.error(request, "Choose a .zip of your codebase to import.")
                    return redirect("dashboard:import")
                if upload.size > 20 * 1024 * 1024:
                    messages.error(request, "Archive too large (max 20 MB for now).")
                    return redirect("dashboard:import")
                archive = upload
            files = extract_zip(archive)
        except IngestError as exc:
            messages.error(request, str(exc))
            return redirect("dashboard:import")

        project = Project.objects.create(
            organization=org, name=name, mode="import", created_by=request.user
        )
        project.ensure_default_workspace()
        summary = import_codebase(project, files, created_by=request.user)
        stack = ", ".join(f"{r}: {t}" for r, t in summary["stack"].items()) or "unknown stack"
        origin = f"from {PROVIDERS.get(request.POST.get('provider'), 'Git')} " if source == "git" else ""
        messages.success(
            request,
            f"Imported {summary['files']} files {origin}· detected {stack}. "
            "DevForge now understands this app — request changes below.",
        )
        return redirect("dashboard:project", pk=project.id)

    return render(request, "dashboard/import.html", {
        "active": "analyze-software", "manageable_orgs": manageable,
    })


@login_required
def change_detail(request, pk):
    change = get_object_or_404(
        ChangeRequest.objects.filter(
            project__organization__in=organizations_for(request.user)
        ).select_related("project"),
        pk=pk,
    )
    can_manage = change.project.organization_id in _manageable_ids(request.user)
    if request.method == "POST":
        if not can_manage:
            messages.error(request, "Owner or admin required.")
            return redirect("dashboard:change", pk=pk)
        action = request.POST.get("action")
        if action == "approve":
            changes_service.approve(change, request.user)
            messages.success(request, "Change approved.")
        elif action == "implement":
            changes_service.implement(change)
            messages.success(request, "Change implemented — agents ran against the project.")
        return redirect("dashboard:change", pk=pk)

    tasks = AgentTask.objects.filter(id__in=change.task_ids or [])
    areas = (change.plan or {}).get("affected_areas", {})
    return render(request, "dashboard/change.html", {
        "active": "projects", "change": change, "can_manage": can_manage,
        "areas": areas, "tasks": tasks,
    })


def _handle_project_action(request, proj):
    action = request.POST.get("action")
    orch = Orchestrator()
    if action == "create_task":
        key = request.POST.get("agent_key")
        if key in agent_registry:
            orch.create_task(project=proj, agent_key=key,
                             input={"brief": (request.POST.get("brief") or "").strip()},
                             created_by=request.user)
            messages.success(request, f"Queued a {key} task.")
        else:
            messages.error(request, "Unknown agent.")
    elif action == "run":
        processed = orch.run_ready(proj)
        messages.success(request, f"Ran {len(processed)} task(s).")
    elif action == "select_stack":
        chosen = {r: request.POST.get(r) for r in ROLES if request.POST.get(r) in tech_registry}
        proj.technology = {**(proj.technology or {}), **chosen}
        proj.save(update_fields=["technology", "updated_at"])
        messages.success(request, "Stack updated.")


# --- engineering / project lists (real data) --------------------------------

@login_required
def agents(request):
    return render(request, "dashboard/agents.html", {
        "active": "agents", "agents": agent_registry.all(),
    })


@login_required
def tasks(request):
    orgs = organizations_for(request.user)
    rows = (
        AgentTask.objects.filter(project__organization__in=orgs)
        .select_related("project").order_by("-created_at")[:100]
    )
    return render(request, "dashboard/tasks.html", {"active": "tasks", "tasks": rows})


@login_required
def deployments(request):
    orgs = organizations_for(request.user)
    rows = (
        Deployment.objects.filter(project__organization__in=orgs)
        .select_related("project").order_by("-created_at")[:100]
    )
    return render(request, "dashboard/deployments.html", {"active": "deployments", "deployments": rows})


@login_required
def usage(request):
    orgs = list(organizations_for(request.user))
    records = (
        UsageRecord.objects.filter(organization__in=orgs)
        .select_related("project").order_by("-created_at")[:100]
    )
    spend = sum((r.cost_usd for r in records), Decimal("0"))
    credits = sum((r.credits_charged for r in records), Decimal("0"))
    accounts = CreditAccount.objects.filter(organization__in=orgs)
    return render(request, "dashboard/usage.html", {
        "active": "usage", "records": records, "spend": spend,
        "credits": credits, "accounts": accounts,
    })


# --- honest placeholder for areas without a backend yet ---------------------

@login_required
def soon(request, slug):
    return render(request, "dashboard/soon.html", {
        "active": slug, "title": slug.replace("-", " ").title(),
    })
