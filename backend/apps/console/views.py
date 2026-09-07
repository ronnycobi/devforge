"""Internal staff console — DevForge's cross-tenant operations cockpit.

Read-first: every page surfaces real platform state (no fabrication). Unlike the
customer dashboard, this is where the machinery is legitimately visible —
orchestrator activity, model routing, and unit economics — because the audience
is DevForge staff, not customers.
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Count, DecimalField, Q, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from apps.accounts.models import User
from apps.changes.models import ChangeRequest
from apps.console.access import staff_required
from apps.credits.models import CreditAccount, UsageRecord
from apps.deployments.models import Deployment
from apps.marketing.models import ContactMessage
from apps.orchestrator.models import TERMINAL_STATUSES, AgentTask, TaskStatus
from apps.organizations.models import Membership, Organization
from apps.projects.models import Project

_MONEY = DecimalField(max_digits=16, decimal_places=4)


def _zero():
    return Coalesce(Sum("cost_usd"), Decimal("0"), output_field=_MONEY)


def _usage_totals(qs=None):
    qs = UsageRecord.objects.all() if qs is None else qs
    agg = qs.aggregate(
        cost=Coalesce(Sum("cost_usd"), Decimal("0"), output_field=_MONEY),
        credits=Coalesce(Sum("credits_charged"), Decimal("0"), output_field=_MONEY),
        tokens=Coalesce(Sum("total_tokens"), 0),
    )
    return agg


@staff_required
def overview(request):
    active_statuses = [s for s in TaskStatus.values if s not in TERMINAL_STATUSES]
    totals = _usage_totals()
    stats = {
        "orgs": Organization.objects.count(),
        "users": User.objects.count(),
        "projects": Project.objects.count(),
        "active_tasks": AgentTask.objects.filter(status__in=active_statuses).count(),
        "deployments": Deployment.objects.count(),
        "cost_usd": totals["cost"],
        "credits_charged": totals["credits"],
        "open_leads": ContactMessage.objects.count(),
    }
    recent_tasks = (
        AgentTask.objects.select_related("project", "project__organization")
        .order_by("-created_at")[:12]
    )
    recent_orgs = Organization.objects.order_by("-created_at")[:6]
    awaiting = AgentTask.objects.filter(
        status=TaskStatus.WAITING_FOR_APPROVAL
    ).select_related("project").count()
    return render(request, "console/overview.html", {
        "active": "overview", "stats": stats,
        "recent_tasks": recent_tasks, "recent_orgs": recent_orgs, "awaiting": awaiting,
    })


@staff_required
def organizations(request):
    rows = (
        Organization.objects.annotate(
            n_members=Count("memberships", distinct=True),
            n_projects=Count("projects", distinct=True),
        )
        .select_related()
        .order_by("-created_at")
    )
    accounts = {a.organization_id: a for a in CreditAccount.objects.all()}
    spend = {
        r["organization"]: r["c"]
        for r in UsageRecord.objects.values("organization").annotate(c=_zero())
    }
    data = [
        {"org": o, "account": accounts.get(o.id), "spend": spend.get(o.id, Decimal("0"))}
        for o in rows
    ]
    return render(request, "console/organizations.html", {"active": "orgs", "rows": data})


@staff_required
def organization_detail(request, pk):
    org = get_object_or_404(Organization, pk=pk)
    members = Membership.objects.filter(organization=org).select_related("user")
    projects = Project.objects.filter(organization=org).order_by("-created_at")
    account = CreditAccount.objects.filter(organization=org).first()
    totals = _usage_totals(UsageRecord.objects.filter(organization=org))
    recent = UsageRecord.objects.filter(organization=org).order_by("-created_at")[:15]
    return render(request, "console/organization_detail.html", {
        "active": "orgs", "org": org, "members": members, "projects": projects,
        "account": account, "totals": totals, "recent_usage": recent,
    })


@staff_required
def users(request):
    rows = (
        User.objects.annotate(n_orgs=Count("memberships", distinct=True))
        .order_by("-date_joined")
    )
    return render(request, "console/users.html", {
        "active": "users", "rows": rows,
        "staff_count": User.objects.filter(is_staff=True).count(),
    })


@staff_required
def projects(request):
    rows = (
        Project.objects.select_related("organization", "created_by")
        .annotate(
            n_tasks=Count("agent_tasks", distinct=True),
            n_done=Count("agent_tasks", filter=Q(agent_tasks__status=TaskStatus.COMPLETED), distinct=True),
        )
        .order_by("-created_at")
    )
    return render(request, "console/projects.html", {"active": "projects", "rows": rows})


@staff_required
def tasks(request):
    status = request.GET.get("status") or ""
    qs = AgentTask.objects.select_related("project", "project__organization").order_by("-created_at")
    if status:
        qs = qs.filter(status=status)
    counts = {
        r["status"]: r["n"]
        for r in AgentTask.objects.values("status").annotate(n=Count("id"))
    }
    statuses = [
        {"value": v, "label": label, "count": counts.get(v, 0)}
        for v, label in TaskStatus.choices
    ]
    return render(request, "console/tasks.html", {
        "active": "tasks", "rows": qs[:200], "statuses": statuses, "current": status,
    })


@staff_required
def economics(request):
    totals = _usage_totals()
    margin = totals["credits"] - totals["cost"]
    by_model = (
        UsageRecord.objects.values("provider", "model")
        .annotate(cost=_zero(), credits=Coalesce(Sum("credits_charged"), Decimal("0"), output_field=_MONEY),
                  tokens=Coalesce(Sum("total_tokens"), 0), n=Count("id"))
        .order_by("-cost")
    )
    by_agent = (
        UsageRecord.objects.values("agent_key")
        .annotate(cost=_zero(), n=Count("id"))
        .order_by("-cost")[:12]
    )
    return render(request, "console/economics.html", {
        "active": "economics", "totals": totals, "margin": margin,
        "by_model": by_model, "by_agent": by_agent,
    })


@staff_required
def deployments(request):
    rows = (
        Deployment.objects.select_related("project", "project__organization")
        .order_by("-created_at")[:200]
    )
    return render(request, "console/deployments.html", {"active": "deployments", "rows": rows})


@staff_required
def leads(request):
    rows = ContactMessage.objects.order_by("-created_at")[:200]
    return render(request, "console/leads.html", {"active": "leads", "rows": rows})
