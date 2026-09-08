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
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

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
from apps.organizations import invitations as invites
from apps.organizations.models import (
    Invitation,
    InvitationStatus,
    Membership,
    Organization,
    Role,
    Team,
)
from apps.orchestrator.models import TERMINAL_STATUSES, AgentTask
from apps.orchestrator.service import Orchestrator
from apps.project_context.models import ContextEntry, ContextKind
from apps.projects.models import Project
from apps.workspaces.models import Workspace
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
def people(request):
    """Members, invitations, and teams for the user's organizations."""
    orgs = list(organizations_for(request.user))
    manageable = _manageable_ids(request.user)

    if request.method == "POST":
        org = get_object_or_404(Organization, pk=request.POST.get("organization", 0))
        if not Membership.objects.filter(organization=org, user=request.user).exists():
            messages.error(request, "Not your organization.")
            return redirect("dashboard:people")
        can_manage = org.id in manageable
        action = request.POST.get("action")
        if not can_manage:
            messages.error(request, "Owner or admin rights required.")
            return redirect("dashboard:people")
        try:
            if action == "invite":
                team = None
                if request.POST.get("team"):
                    team = Team.objects.filter(pk=request.POST["team"], organization=org).first()
                inv = invites.create_invitation(
                    org, request.POST.get("email", ""),
                    role=request.POST.get("role") or Role.MEMBER,
                    team=team, invited_by=request.user,
                )
                link = request.build_absolute_uri(
                    reverse("dashboard:accept_invite", args=[inv.token])
                )
                from apps.notifications.email import send_invitation_email
                try:
                    sent = send_invitation_email(inv, link)
                except Exception:
                    sent = 0  # delivery failed; the invite still stands, link below
                note = "invitation email sent" if sent else "email not delivered"
                messages.success(request, f"Invited {inv.email} ({note}). Link: {link}")
            elif action == "revoke":
                inv = get_object_or_404(Invitation, pk=request.POST.get("invitation", 0), organization=org)
                invites.revoke_invitation(inv)
                messages.success(request, f"Revoked the invite for {inv.email}.")
            elif action == "create_team":
                name = (request.POST.get("name") or "").strip()
                if name:
                    Team.objects.create(organization=org, name=name)
                    messages.success(request, f"Team “{name}” created.")
                else:
                    messages.error(request, "Team name required.")
        except invites.InvitationError as exc:
            messages.error(request, str(exc))
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("dashboard:people")

    cards = []
    for o in orgs:
        cards.append({
            "org": o,
            "can_manage": o.id in manageable,
            "members": Membership.objects.filter(organization=o).select_related("user"),
            "invites": Invitation.objects.filter(organization=o, status=InvitationStatus.PENDING),
            "teams": Team.objects.filter(organization=o).prefetch_related("members"),
            "roles": Role.choices,
        })
    return render(request, "dashboard/people.html", {"active": "people", "cards": cards})


@login_required
def accept_invite(request, token):
    """Accept an organization invitation via its token (must be logged in)."""
    try:
        membership = invites.accept_invitation(token, request.user)
        messages.success(
            request, f"You’ve joined {membership.organization.name} as {membership.role}."
        )
    except invites.InvitationError as exc:
        messages.error(request, str(exc))
    return redirect("dashboard:people")


@login_required
def security(request):
    """Per-project security posture from the twin's SECURITY findings, plus an
    on-demand scan (runs the deterministic Security Agent)."""
    orgs = list(organizations_for(request.user))
    manageable = _manageable_ids(request.user)

    if request.method == "POST" and request.POST.get("action") == "run_scan":
        proj = get_object_or_404(
            Project, pk=request.POST.get("project", 0), organization__in=orgs
        )
        if proj.organization_id not in manageable:
            messages.error(request, "Owner or admin rights required to run a scan.")
        else:
            orch = Orchestrator()
            task = orch.create_task(
                project=proj, agent_key="security", input={}, created_by=request.user
            )
            orch.run_task(task)
            task.refresh_from_db()
            note = task.messages[-1] if task.messages else "Scan complete."
            messages.success(request, f"{proj.name}: {note}")
        return redirect("dashboard:security")

    rows = []
    for p in Project.objects.filter(organization__in=orgs).select_related("organization"):
        entries = list(
            ContextEntry.objects.filter(project=p, kind=ContextKind.SECURITY)
        )
        counts = {"high": 0, "medium": 0, "low": 0}
        for e in entries:
            sev = (e.data or {}).get("severity", "low")
            if sev in counts:
                counts[sev] += 1
        rows.append({
            "project": p, "counts": counts, "total": len(entries),
            "findings": entries[:25], "can_manage": p.organization_id in manageable,
        })
    return render(request, "dashboard/security.html", {"active": "security", "rows": rows})


@login_required
def change_detail(request, pk):
    change = get_object_or_404(
        ChangeRequest.objects.filter(
            project__organization__in=organizations_for(request.user)
        ).select_related("project", "migration"),
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
        elif action == "rollback":
            if change.can_rollback:
                changes_service.rollback(change)
                messages.success(request, "Change rolled back — repo restored to its pre-change state.")
            else:
                messages.error(request, "This change can't be rolled back.")
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


# --- Real workspace pages (were SOON) ---------------------------------------

_SECTION = {
    "apis": ([ContextKind.API], "APIs", "HTTP endpoints DevForge has designed for your apps."),
    "database": ([ContextKind.SCHEMA], "Database", "Data models, detected databases, and migrations."),
    "tests": ([ContextKind.TESTING], "Tests", "Test cases DevForge has designed across your projects."),
    "code-issues": ([ContextKind.REVIEW, ContextKind.SECURITY], "Code Issues",
                    "Review findings and security scan results across your projects."),
}


@login_required
def section(request, slug):
    """A slice of the digital twin (APIs / schema / tests / issues) per project."""
    meta = _SECTION.get(slug)
    if meta is None:
        raise Http404
    kinds, title, sub = meta
    from apps.database.models import DatabaseMigration
    rows = []
    for p in Project.objects.filter(
        organization__in=organizations_for(request.user)
    ).select_related("organization"):
        entries = list(ContextEntry.objects.filter(project=p, kind__in=kinds))
        extra = {}
        if slug == "database":
            extra = {"db": (p.technology or {}).get("database"),
                     "migrations": DatabaseMigration.objects.filter(project=p).count()}
        if entries or extra.get("db") or extra.get("migrations"):
            rows.append({"project": p, "entries": entries[:60], "count": len(entries), **extra})
    return render(request, "dashboard/section.html", {
        "active": slug, "title": title, "sub": sub, "rows": rows, "slug": slug,
    })


@login_required
def repository(request):
    """Browse the generated source and git history of each project."""
    from apps.repositories.service import repo_for_project
    rows = []
    for p in Project.objects.filter(
        organization__in=organizations_for(request.user)
    ).select_related("organization"):
        repo = repo_for_project(p)
        if not repo.is_initialized:
            rows.append({"project": p, "files": [], "log": []})
            continue
        rows.append({"project": p, "files": repo.list_files()[:100], "log": repo.log(10)})
    return render(request, "dashboard/repository.html", {"active": "repository", "rows": rows})


@login_required
def templates_page(request):
    """Starter templates = the technology stacks DevForge can build and run."""
    from apps.technology.stacks import all_stacks
    stacks = [
        {"id": s.id, "language": s.language, "framework": s.framework,
         "kind": s.kind, "runnable": s.is_runnable()}
        for s in all_stacks()
    ]
    return render(request, "dashboard/templates.html", {"active": "templates", "stacks": stacks})


@login_required
def settings_page(request):
    """Project settings: rename / describe / delete (owner/admin)."""
    orgs = list(organizations_for(request.user))
    manageable = _manageable_ids(request.user)
    if request.method == "POST":
        proj = get_object_or_404(Project, pk=request.POST.get("project", 0), organization__in=orgs)
        if proj.organization_id not in manageable:
            messages.error(request, "Owner or admin rights required.")
            return redirect("dashboard:settings")
        action = request.POST.get("action")
        if action == "rename":
            name = (request.POST.get("name") or "").strip()
            if name:
                proj.name = name
                proj.description = (request.POST.get("description") or "").strip()
                proj.save(update_fields=["name", "description", "updated_at"])
                messages.success(request, "Project updated.")
        elif action == "delete":
            proj.delete()
            messages.success(request, "Project deleted.")
        return redirect("dashboard:settings")
    rows = [
        {"project": p, "can_manage": p.organization_id in manageable}
        for p in Project.objects.filter(organization__in=orgs).select_related("organization")
    ]
    return render(request, "dashboard/settings.html", {"active": "settings", "rows": rows})


_OPS = {
    "environments": "Environments", "cloud": "Cloud", "infrastructure": "Infrastructure",
    "monitoring": "Monitoring", "logs": "Logs", "incidents": "Incidents",
    "scaling": "Scaling", "performance": "Performance", "modernization": "Modernization",
}
# Areas that need a live connection before they can show real metrics.
_OPS_NEEDS_CONNECTION = {
    "monitoring": "a monitored, deployed environment",
    "incidents": "monitoring connected to a live deployment",
    "scaling": "live traffic and resource metrics from a deployment",
    "performance": "profiling data from a running app",
    "infrastructure": "a connected cloud/infrastructure provider",
}


@login_required
def operations(request, area):
    """Deploy/operate pages. Shows real adjacent state; never invents metrics."""
    if area not in _OPS:
        raise Http404
    orgs = organizations_for(request.user)
    ctx = {"active": area, "title": _OPS[area], "area": area,
           "needs": _OPS_NEEDS_CONNECTION.get(area)}
    if area == "environments":
        ctx["workspaces"] = Workspace.objects.filter(
            project__organization__in=orgs).select_related("project")
        ctx["deployments"] = Deployment.objects.filter(
            project__organization__in=orgs).select_related("project").order_by("-created_at")[:50]
    elif area == "cloud":
        from apps.deployments.providers import provider_status
        ctx["providers"] = provider_status()
    elif area == "logs":
        ctx["tasks"] = AgentTask.objects.filter(
            project__organization__in=orgs).select_related("project").order_by("-created_at")[:60]
    elif area == "modernization":
        ctx["imports"] = Project.objects.filter(
            organization__in=orgs, mode="import").select_related("organization")
    return render(request, "dashboard/operations.html", ctx)
