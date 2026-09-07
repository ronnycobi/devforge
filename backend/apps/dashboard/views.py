"""Server-rendered Django UI for DevForge (the control-plane web app).

Session-authenticated, tenant-scoped through org membership. This is DevForge's
own operator UI — distinct from the software DevForge generates for customers.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.agents.definitions import registry as agent_registry
from apps.organizations.access import (
    manageable_organizations_for,
    organizations_for,
)
from apps.organizations.models import Organization
from apps.orchestrator.service import Orchestrator
from apps.project_context.models import ContextEntry, ContextKind
from apps.projects.models import Project
from apps.technology.registry import ROLES
from apps.technology.registry import registry as tech_registry

# Context kinds shown as the "project workspace" pipeline, in order.
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


def _manageable_ids(user):
    return set(manageable_organizations_for(user).values_list("id", flat=True))


@login_required
def dashboard(request):
    orgs = list(organizations_for(request.user))
    manageable = _manageable_ids(request.user)

    if request.method == "POST" and request.POST.get("action") == "create_project":
        org = get_object_or_404(Organization, pk=request.POST.get("organization", 0))
        name = (request.POST.get("name") or "").strip()
        if org.id in manageable and name:
            project = Project.objects.create(
                organization=org, name=name, created_by=request.user
            )
            project.ensure_default_workspace()
            messages.success(request, f"Created project “{project.name}”.")
            return redirect("dashboard:project", pk=project.id)
        messages.error(request, "Need a name and owner/admin rights in that org.")
        return redirect("dashboard:home")

    projects = (
        Project.objects.filter(organization__in=orgs)
        .select_related("organization")
        .order_by("organization__name", "name")
    )
    return render(
        request,
        "dashboard/dashboard.html",
        {
            "orgs": orgs,
            "manageable_orgs": [o for o in orgs if o.id in manageable],
            "projects": projects,
        },
    )


@login_required
def project(request, pk):
    proj = get_object_or_404(
        Project.objects.filter(organization__in=organizations_for(request.user)),
        pk=pk,
    )
    can_manage = proj.organization_id in _manageable_ids(request.user)

    if request.method == "POST":
        if not can_manage:
            messages.error(request, "Owner or admin required for this action.")
            return redirect("dashboard:project", pk=pk)
        _handle_project_action(request, proj)
        return redirect("dashboard:project", pk=pk)

    entries = ContextEntry.objects.filter(project=proj)
    pipeline = [
        {
            "kind": kind,
            "label": ContextKind(kind).label,
            "entries": [e for e in entries if e.kind == kind],
        }
        for kind in _PIPELINE
    ]
    stack_roles = [
        {
            "role": role,
            "chosen": (proj.technology or {}).get(role),
            "options": tech_registry.options_for_role(role),
        }
        for role in ROLES
    ]
    return render(
        request,
        "dashboard/project.html",
        {
            "project": proj,
            "can_manage": can_manage,
            "pipeline": pipeline,
            "tasks": proj.agent_tasks.select_related("project").all(),
            "agents": agent_registry.all(),
            "stack_roles": stack_roles,
        },
    )


def _handle_project_action(request, proj):
    action = request.POST.get("action")
    orch = Orchestrator()

    if action == "create_task":
        key = request.POST.get("agent_key")
        if key in agent_registry:
            orch.create_task(
                project=proj,
                agent_key=key,
                input={"brief": (request.POST.get("brief") or "").strip()},
                created_by=request.user,
            )
            messages.success(request, f"Queued a {key} task.")
        else:
            messages.error(request, "Unknown agent.")

    elif action == "run":
        processed = orch.run_ready(proj)
        messages.success(request, f"Ran {len(processed)} task(s).")

    elif action == "select_stack":
        chosen = {}
        for role in ROLES:
            value = request.POST.get(role)
            if value and value in tech_registry:
                chosen[role] = value
        proj.technology = {**(proj.technology or {}), **chosen}
        proj.save(update_fields=["technology", "updated_at"])
        messages.success(request, "Stack updated.")
