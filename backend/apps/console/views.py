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


def _open_ticket_count() -> int:
    from apps.support.models import OPEN_STATUSES, SupportTicket
    return SupportTicket.objects.filter(status__in=OPEN_STATUSES).count()


@staff_required
def overview(request):
    active_statuses = [s for s in TaskStatus.values if s not in TERMINAL_STATUSES]
    totals = _usage_totals()

    completed = AgentTask.objects.filter(status=TaskStatus.COMPLETED).count()
    failed = AgentTask.objects.filter(status=TaskStatus.FAILED).count()
    finished = completed + failed
    success_rate = round(completed / finished * 100) if finished else None

    stats = {
        "orgs": Organization.objects.count(),
        "users": User.objects.count(),
        "projects": Project.objects.count(),
        "builds": AgentTask.objects.count(),
        "active_tasks": AgentTask.objects.filter(status__in=active_statuses).count(),
        "success_rate": success_rate,
        "deployments": Deployment.objects.count(),
        "cost_usd": totals["cost"],
        "credits_charged": totals["credits"],
        "open_leads": ContactMessage.objects.count(),
        "open_tickets": _open_ticket_count(),
    }

    from apps.console.health import all_ok, system_health
    health = system_health()

    # Live activity: the real audit trail, newest first.
    from apps.audit.models import AuditEvent
    activity = (
        AuditEvent.objects.select_related("actor", "organization").order_by("-created_at")[:12]
    )
    recent_orgs = Organization.objects.order_by("-created_at")[:6]
    awaiting = AgentTask.objects.filter(status=TaskStatus.WAITING_FOR_APPROVAL).count()
    return render(request, "console/overview.html", {
        "active": "overview", "stats": stats,
        "health": health, "health_ok": all_ok(health),
        "activity": activity, "recent_orgs": recent_orgs, "awaiting": awaiting,
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
    from apps.credits.services import daily_usd_cap, spent_today
    cap = daily_usd_cap(account) if account else None
    return render(request, "console/organization_detail.html", {
        "active": "orgs", "org": org, "members": members, "projects": projects,
        "account": account, "totals": totals, "recent_usage": recent,
        "spent_today": spent_today(org), "daily_cap": cap,
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


@staff_required
def mobile_releases(request):
    """Admin view of the Mobile Release & App Store Platform (spec §30). Read-only,
    honest: shows store-provider availability, connections, and every release across
    tenants so staff can diagnose failures without exposing internals to customers."""
    from apps.release.models import MobileApplication, Release, ReleaseRejection, StoreConnection
    from apps.release.providers import provider_status
    rejections = (
        ReleaseRejection.objects.select_related(
            "release", "release__mobile_application", "release__mobile_application__project__organization")
        .order_by("-created_at")[:50]
    )
    releases = (
        Release.objects.select_related("mobile_application", "mobile_application__project",
                                        "mobile_application__project__organization")
        .order_by("-created_at")[:200]
    )
    connections = (
        StoreConnection.objects.select_related("organization").order_by("-created_at")[:100]
    )
    apps = (
        MobileApplication.objects.select_related("project", "project__organization")
        .order_by("-created_at")[:100]
    )
    return render(request, "console/mobile_releases.html", {
        "active": "mobile", "providers": provider_status(),
        "releases": releases, "connections": connections, "apps": apps,
        "rejections": rejections,
    })


@staff_required
def skills(request):
    """Skills library (Control Center). Lists the built-in global playbooks and any
    DB-authored ones; staff can add a global skill."""
    from django.utils.text import slugify
    from apps.skills.builtins import BUILTIN_SKILLS
    from apps.skills.models import Skill
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        kws = [k.strip() for k in (request.POST.get("keywords") or "").split(",") if k.strip()]
        body = (request.POST.get("body") or "").strip()
        if name and body:
            Skill.objects.create(
                name=name, slug=slugify(name)[:64] or "skill", keywords=kws, body=body,
                scope=Skill.SCOPE_GLOBAL, created_by=request.user)
        from django.shortcuts import redirect
        return redirect("console:skills")
    return render(request, "console/skills.html", {
        "active": "skills",
        "builtins": BUILTIN_SKILLS,
        "authored": Skill.objects.select_related("organization", "project"),
    })


@staff_required
def connectors(request):
    """External connectors inventory (spec: MCP-style layer). Honest: shows each
    connector and whether it's configured — never the credential value."""
    from apps.tools.connectors import connector_status
    return render(request, "console/connectors.html", {
        "active": "connectors", "connectors": connector_status(),
    })


@staff_required
def websites(request):
    """Admin view of the Website Publishing platform (spec §43). Read-only, honest:
    host availability, every website, and its publish versions across tenants."""
    from apps.publishing.hosting import host_status
    from apps.publishing.models import CustomDomain, PublishVersion, Website
    sites = (
        Website.objects.select_related("project", "project__organization").order_by("-created_at")[:100]
    )
    versions = (
        PublishVersion.objects.select_related("website", "website__project__organization")
        .order_by("-created_at")[:200]
    )
    domains = (
        CustomDomain.objects.select_related("website", "website__project__organization")
        .order_by("-created_at")[:100]
    )
    return render(request, "console/websites.html", {
        "active": "websites", "hosts": host_status(), "sites": sites,
        "versions": versions, "domains": domains,
    })


@staff_required
def audit(request):
    from apps.audit.models import AuditEvent
    action = request.GET.get("action") or ""
    qs = AuditEvent.objects.select_related("actor", "organization").order_by("-created_at")
    if action:
        qs = qs.filter(action=action)
    actions = sorted(
        AuditEvent.objects.values_list("action", flat=True).distinct()
    )
    return render(request, "console/audit.html", {
        "active": "audit", "rows": qs[:300], "actions": actions, "current": action,
    })
