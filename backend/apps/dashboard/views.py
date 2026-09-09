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
from apps.credits.models import CreditAccount, Invoice, UsageRecord
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
from apps.project_context.services import ProjectContext
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


# --- Home: the builder ("What do you want to build?") -----------------------

_STARTERS = [
    ("CRM", "Build a CRM with contacts, companies, leads, deals, activities and a sales dashboard."),
    ("Website", "Build a professional website for my business with home, services, about and contact pages."),
    ("SaaS", "Build a SaaS platform where teams sign up, manage members and pay a monthly subscription."),
    ("E-commerce", "Build an online store with a product catalog, cart, checkout and orders."),
    ("Customer Portal", "Build a customer portal where clients log in, submit requests and track their status."),
    ("Internal Tool", "Build an internal tool for my team to manage tasks, approvals and reports."),
    ("Mobile App", "Build a mobile-friendly app for booking appointments with reminders."),
    ("API", "Build a REST API for managing customers, orders and invoices."),
]
_PLACEHOLDERS = [
    "Build a CRM for my sales team with customers, leads, deals, tasks and a dashboard…",
    "Build an e-commerce website for my clothing business…",
    "Create a booking system for my salon…",
    "Build a construction project management app…",
    "Create a website for my engineering company…",
    "Build a mobile-friendly invoicing system…",
    "Create a SaaS platform for managing employees and leave…",
]
_BUILD_PIPELINE = ["requirements", "architect", "database", "backend",
                   "frontend", "testing", "code_review", "security"]


def _name_from_brief(brief: str) -> str:
    import re
    text = re.sub(r"^\s*(please\s+)?(build|create|make|develop|design)\s+(me\s+)?(a|an|the)?\s*",
                  "", brief.strip(), flags=re.I)
    words = text.split()
    name = " ".join(words[:6]).rstrip(".,").strip()
    return (name[:60] or "New project").title()


def _start_build(project, brief, user):
    orch = Orchestrator()
    previous = None
    for key in _BUILD_PIPELINE:
        t = orch.create_task(project=project, agent_key=key,
                             input={"brief": brief}, created_by=user)
        if previous is not None:
            t.depends_on.set([previous])
        previous = t
    orch.run_ready(project)


@login_required
def overview(request):
    user = request.user
    orgs = list(organizations_for(user))
    manageable = _manageable_ids(user)

    if request.method == "POST" and request.POST.get("action") == "build":
        brief = (request.POST.get("brief") or "").strip()
        if not brief:
            messages.error(request, "Tell DevForge what you want to build.")
            return redirect("dashboard:home")
        org = next((o for o in orgs if o.id in manageable), None)
        if org is None:
            org = Organization.objects.create(
                name=f"{user.short_name}'s workspace", created_by=user)
            org.add_member(user, role=Role.OWNER)
        project = Project.objects.create(
            organization=org, name=_name_from_brief(brief),
            created_by=user, description=brief[:500])
        project.ensure_default_workspace()
        ProjectContext(project).set(
            ContextKind.REQUIREMENT, "brief", title="What to build",
            content=brief, source="builder")
        _start_build(project, brief, user)
        messages.success(request, "DevForge is building your project.")
        return redirect("dashboard:project", pk=project.id)

    projects = Project.objects.filter(
        organization__in=orgs).select_related("organization").order_by("-updated_at")
    cards = [
        {"project": p, "state": _project_state(p), "progress": _project_progress(p)}
        for p in projects[:12]
    ]
    return render(request, "dashboard/home.html", {
        "active": "overview", "cards": cards,
        "starters": _STARTERS, "placeholders": _PLACEHOLDERS,
        "prefill": request.session.pop("build_idea", ""),  # carried from marketing signup
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
    from apps.capabilities.infer import infer_capabilities
    return render(request, "dashboard/project.html", {
        "active": "projects", "project": proj, "can_manage": can_manage,
        "state": _project_state(proj), "progress": _project_progress(proj),
        "pipeline": pipeline, "tasks": proj.agent_tasks.all(),
        "stack_roles": stack_roles,
        "capabilities": infer_capabilities(proj.description or proj.name),
        "twin": twin, "changes": proj.changes.all()[:8],
        "backups": proj.backups.all()[:10],
    })


@login_required
def release_center(request, pk):
    """Mobile Release Center (spec §19): one page to prepare and release a mobile
    app to Google Play, App Store and AppGallery. Every store shows its REAL state
    — not connected here, because live publishing needs the customer's own store
    credentials — and readiness is computed from actual records. Nothing is faked.
    """
    from apps.release import service as rel
    from apps.release.models import MobileApplication
    from apps.release.providers import all_providers, get_provider

    proj = get_object_or_404(
        Project.objects.filter(organization__in=organizations_for(request.user)), pk=pk
    )
    can_manage = proj.organization_id in _manageable_ids(request.user)
    app = MobileApplication.objects.filter(project=proj).order_by("created_at").first()

    if request.method == "POST":
        if not can_manage:
            messages.error(request, "Owner or admin required for this action.")
            return redirect("dashboard:release_center", pk=pk)
        action = request.POST.get("action")
        if action == "create_app":
            # Idempotent: reuse an existing app rather than creating a duplicate.
            if app is None:
                slug = (proj.slug or proj.name).lower().replace("-", "").replace(" ", "")
                pkg = f"com.devforge.{slug}"[:250] or "com.devforge.app"
                app = rel.create_mobile_application(
                    project=proj, name=proj.name, package_identifier=pkg, bundle_identifier=pkg,
                )
            from apps.release.models import StoreMetadata
            for prov in all_providers():
                store_app = rel.ensure_store_application(app, prov.key)
                if not StoreMetadata.objects.filter(store_application=store_app).exists():
                    rel.set_metadata(store_app, app_name=app.name)
            messages.success(request, "Mobile application ready. Connect your store accounts to publish.")
        elif action == "generate_listing" and app:
            store_app = app.store_apps.filter(provider=request.POST.get("provider")).first()
            if store_app:
                rel.generate_store_listing(store_app, user=request.user)
                messages.success(request, "Drafted an AI store listing from your app's "
                                          "features — review and approve it below.")
        elif action == "save_listing" and app:
            store_app = app.store_apps.filter(provider=request.POST.get("provider")).first()
            if store_app:
                rel.set_metadata(
                    store_app, ai_generated=False, approved=False,
                    app_name=(request.POST.get("app_name") or "")[:255],
                    short_description=(request.POST.get("short_description") or "")[:255],
                    full_description=request.POST.get("full_description") or "",
                    privacy_url=request.POST.get("privacy_url") or "",
                )
                messages.success(request, "Listing saved.")
        elif action == "approve_listing" and app:
            store_app = app.store_apps.filter(provider=request.POST.get("provider")).first()
            if store_app:
                rel.approve_metadata(store_app, user=request.user)
                messages.success(request, "Listing approved.")
        elif action == "generate_screenshots" and app:
            store_app = app.store_apps.filter(provider=request.POST.get("provider")).first()
            if store_app:
                shots = rel.generate_store_screenshots(store_app, user=request.user)
                if shots:
                    messages.success(request, f"Generated {len(shots)} layout preview(s) from "
                                              "your app's screens — review and approve them.")
                else:
                    messages.warning(request, "No screens detected yet to generate previews from.")
        elif action == "approve_screenshots" and app:
            store_app = app.store_apps.filter(provider=request.POST.get("provider")).first()
            if store_app:
                n = rel.approve_screenshots(store_app, user=request.user)
                messages.success(request, f"Approved {n} screenshot(s).")
        elif action == "report_rejection" and app:
            release = app.releases.filter(provider=request.POST.get("provider")).first()
            text = (request.POST.get("rejection_text") or "").strip()
            if release and text:
                record = rel.record_rejection(release, text=text, source="manual", user=request.user)
                messages.success(request, f"Analysed the rejection — “{record.label}”. "
                                          "Review the suggested fix below.")
            else:
                messages.error(request, "Prepare a release first, then paste the store's message.")
        elif action == "plan_fix" and app:
            from apps.release.models import ReleaseRejection
            rejection = ReleaseRejection.objects.filter(
                pk=request.POST.get("rejection", 0),
                release__mobile_application__project=proj).first()
            if rejection and not rejection.change:
                change = rel.plan_fix(rejection, user=request.user)
                return redirect("dashboard:change", pk=change.id)
        elif action == "resubmit" and app:
            release = app.releases.filter(pk=request.POST.get("release", 0)).first()
            if release:
                new_release = rel.prepare_resubmission(release, user=request.user)
                messages.success(request, f"Prepared v{new_release.version}+{new_release.build_number} "
                                          "for resubmission.")
        elif action == "prepare_release" and app:
            provider_key = request.POST.get("provider")
            if get_provider(provider_key):
                release = rel.request_release(app=app, provider_key=provider_key, user=request.user)
                messages.success(
                    request, f"Prepared a release for {get_provider(provider_key).name} "
                             f"({release.readiness}% ready)."
                )
            else:
                messages.error(request, "Unknown store.")
        elif action == "approve_release" and app:
            release = app.releases.filter(pk=request.POST.get("release", 0)).first()
            if release:
                rel.approve_release(release, user=request.user)
                messages.success(request, "Release approved for submission.")
        elif action == "submit_release" and app:
            release = app.releases.filter(pk=request.POST.get("release", 0)).first()
            if release:
                release = rel.submit_release(release, user=request.user)
                if release.state == "submitted":
                    messages.success(request, "Submitted to the store.")
                else:
                    last = release.events.first()
                    messages.warning(request, last.message if last else "Store not connected.")
        return redirect("dashboard:release_center", pk=pk)

    stores = []
    for prov in all_providers():
        conn = proj.organization.store_connections.filter(provider=prov.key).first()
        store_app = app.store_apps.filter(provider=prov.key).first() if app else None
        release = (app.releases.filter(provider=prov.key).first() if app else None)
        shots = list(store_app.assets.filter(kind="screenshot")) if store_app else []
        rejections = list(release.rejections.filter(resolved=False)) if release else []
        stores.append({
            "provider": prov, "connection": conn, "store_app": store_app, "release": release,
            "connected": bool(conn and conn.status == "connected"),
            "screenshots": shots,
            "screenshots_approved": bool(shots) and all(s.approved for s in shots),
            "rejections": rejections,
        })
    return render(request, "dashboard/release_center.html", {
        "active": "projects", "project": proj, "can_manage": can_manage,
        "app": app, "stores": stores,
    })


@login_required
def publish_center(request, pk):
    """Website Release Center (spec §41): Publish → Live URL, with an honest publish
    checklist, versioned publishes served by DevForge, health, and rollback. Public
    custom domains + SSL are a Phase-2 gated path, shown as not-yet-available."""
    from apps.publishing import readiness as pub_readiness
    from apps.publishing import service as pub
    proj = get_object_or_404(
        Project.objects.filter(organization__in=organizations_for(request.user)), pk=pk
    )
    can_manage = proj.organization_id in _manageable_ids(request.user)
    website = getattr(proj, "website", None)

    if request.method == "POST":
        if not can_manage:
            messages.error(request, "Owner or admin required for this action.")
            return redirect("dashboard:publish_center", pk=pk)
        action = request.POST.get("action")
        if action == "enable_website":
            website = pub.get_or_create_website(proj)
            messages.success(request, "Website publishing enabled.")
        elif action == "publish" and website:
            version = pub.publish(website, user=request.user)
            if version.state == "live":
                messages.success(request, f"Published {version.version} — your site is live.")
            elif version.state == "needs_attention":
                messages.warning(request, f"Published {version.version}, but the health check "
                                          f"flagged an issue: {version.health_detail}")
            else:
                messages.error(request, version.log or "Publish failed.")
        elif action == "rollback" and website:
            try:
                target = pub.rollback(website, user=request.user)
                messages.success(request, f"Rolled back to {target.version}.")
            except pub.PublishError as exc:
                messages.error(request, str(exc))
        elif action == "health_check" and website and website.current:
            pub.health_check(website.current)
        elif action == "connect_domain" and website:
            from apps.publishing import domain_service as dom
            try:
                dom.connect_domain(website, hostname=request.POST.get("hostname", ""),
                                   user=request.user)
                messages.success(request, "Domain added — set the DNS records shown, then verify.")
            except dom.DomainServiceError as exc:
                messages.error(request, str(exc))
        elif action == "verify_domain" and website:
            from apps.publishing import domain_service as dom
            domain = website.domains.filter(pk=request.POST.get("domain", 0)).first()
            if domain:
                dom.verify_domain(domain, user=request.user)
                if domain.is_verified:
                    messages.success(request, f"{domain.hostname} ownership verified.")
                else:
                    messages.warning(request, domain.detail)
        elif action == "request_ssl" and website:
            from apps.publishing import domain_service as dom
            domain = website.domains.filter(pk=request.POST.get("domain", 0)).first()
            if domain:
                try:
                    dom.request_ssl(domain, user=request.user)
                    messages.info(request, domain.detail)
                except dom.DomainServiceError as exc:
                    messages.error(request, str(exc))
        elif action == "remove_domain" and website:
            from apps.publishing import domain_service as dom
            domain = website.domains.filter(pk=request.POST.get("domain", 0)).first()
            if domain:
                dom.remove_domain(domain, user=request.user)
                messages.success(request, "Domain removed.")
        elif action == "seo_generate" and website:
            from apps.publishing import seo_service as seo
            drafts = seo.generate_drafts(website, user=request.user)
            messages.success(request, f"Drafted SEO for {len(drafts)} page(s) — review and apply.")
        elif action == "seo_approve_all" and website:
            from apps.publishing import seo_service as seo
            config = seo.ensure_config(website)
            n = config.pages.update(approved=True)
            messages.success(request, f"Approved SEO for {n} page(s).")
        elif action == "add_form" and website:
            from apps.publishing import forms_service as forms
            forms.create_form(website, kind=request.POST.get("kind", "contact"), user=request.user)
            messages.success(request, "Form added — copy its embed snippet into your site.")
        elif action == "remove_form" and website:
            form = website.forms.filter(pk=request.POST.get("form", 0)).first()
            if form:
                form.delete()
                messages.success(request, "Form removed.")
        elif action == "seo_apply" and website:
            from apps.publishing import seo_service as seo
            try:
                result = seo.apply_seo(website, user=request.user)
                messages.success(request, f"Applied SEO to {result['pages']} page(s) "
                                          "plus sitemap.xml and robots.txt.")
            except seo.SeoServiceError as exc:
                messages.error(request, str(exc))
        return redirect("dashboard:publish_center", pk=pk)

    checks = pub.evaluate(website) if website else []
    current = website.current if website else None
    return render(request, "dashboard/publish_center.html", {
        "active": "projects", "project": proj, "can_manage": can_manage,
        "website": website, "current": current, "checks": checks,
        "score": pub_readiness.score(checks) if checks else 0,
        "versions": website.versions.all()[:10] if website else [],
        "can_publish": pub_readiness.can_publish(checks) if checks else False,
        "domains": website.domains.all() if website else [],
        "seo": _seo_context(website) if website else None,
        "forms": _forms_context(website, request) if website else None,
        "lead_count": website.leads.count() if website else 0,
    })


def _forms_context(website, request):
    from apps.publishing.forms_service import embed_html
    base = f"{request.scheme}://{request.get_host()}"
    return [{"form": f, "embed": embed_html(f, action_base=base),
             "submissions": f.submissions.filter(is_spam=False).count()}
            for f in website.forms.all()]


def _seo_context(website):
    from apps.publishing import seo
    audits = seo.audit_pages(website)
    config = getattr(website, "seo", None)
    return {
        "audits": audits,
        "score": seo.audit_score(audits),
        "pages": list(config.pages.all()) if config else [],
        "applied_at": config.applied_at if config else None,
    }


@login_required
def site_operations(request, pk):
    """AI operations advisor (spec §37): inspect real signals → explain → recommend →
    fix (via the approval-gated change loop). BUILD → OPERATE → IMPROVE."""
    from apps.publishing import operations as ops
    proj = get_object_or_404(
        Project.objects.filter(organization__in=organizations_for(request.user)), pk=pk
    )
    can_manage = proj.organization_id in _manageable_ids(request.user)
    website = getattr(proj, "website", None)

    if request.method == "POST" and website and can_manage:
        if request.POST.get("action") == "create_fix":
            key = request.POST.get("finding")
            finding = next((f for f in ops.analyze(website) if f.key == key
                            and f.action.get("type") == "change"), None)
            if finding:
                change = changes_service.create_change(
                    proj, f"Operations fix — {finding.title}.\n\n{finding.recommendation}",
                    request.user)
                changes_service.build_plan(change)
                return redirect("dashboard:change", pk=change.id)
        return redirect("dashboard:operations", pk=pk)

    findings = ops.analyze(website) if website else []
    return render(request, "dashboard/site_operations.html", {
        "active": "projects", "project": proj, "can_manage": can_manage,
        "website": website, "findings": findings,
        "summary": ops.summary_line(findings) if website else "",
    })


@login_required
def monitoring(request, pk):
    """Health monitoring for the published site (spec §36). Real serve-health probes;
    remote-server resource metrics are honestly marked not-monitored."""
    from apps.publishing import monitor
    proj = get_object_or_404(
        Project.objects.filter(organization__in=organizations_for(request.user)), pk=pk
    )
    can_manage = proj.organization_id in _manageable_ids(request.user)
    website = getattr(proj, "website", None)

    if request.method == "POST" and website and can_manage:
        if request.POST.get("action") == "run_check":
            if monitor.run_check(website) is None:
                messages.error(request, "Publish the site before running a health check.")
            else:
                messages.success(request, "Health check recorded.")
        return redirect("dashboard:monitoring", pk=pk)

    summary = monitor.uptime_summary(website, days=7) if website else None
    domains = list(website.domains.all()) if website else []
    return render(request, "dashboard/monitoring.html", {
        "active": "projects", "project": proj, "can_manage": can_manage,
        "website": website, "summary": summary, "domains": domains,
    })


@login_required
def accessibility(request, pk):
    """Automated accessibility checks on the built site (spec §30). Reports actual
    findings — never claims guaranteed compliance."""
    from apps.publishing import accessibility as a11y
    proj = get_object_or_404(
        Project.objects.filter(organization__in=organizations_for(request.user)), pk=pk
    )
    website = getattr(proj, "website", None)
    audits = a11y.audit_pages(website) if website else []
    return render(request, "dashboard/accessibility.html", {
        "active": "projects", "project": proj, "website": website,
        "audits": audits, "score": a11y.score(audits) if audits else 0,
    })


@login_required
def analytics(request, pk):
    """Website analytics (spec §28) — real page views of the published site."""
    from apps.publishing import analytics as an
    proj = get_object_or_404(
        Project.objects.filter(organization__in=organizations_for(request.user)), pk=pk
    )
    website = getattr(proj, "website", None)
    try:
        days = max(7, min(90, int(request.GET.get("days", 30))))
    except (TypeError, ValueError):
        days = 30
    data = an.summary(website, days=days) if website else None
    peak = max((p["views"] for p in data["series"]), default=0) if data else 0
    return render(request, "dashboard/analytics.html", {
        "active": "projects", "project": proj, "website": website,
        "data": data, "days": days, "peak": peak or 1,
    })


@login_required
def store(request, pk):
    """Merchant e-commerce console (spec §32): products, orders, manual-payment
    confirmation. Card gateways are shown with their real availability."""
    from apps.publishing import ecommerce_service as shop
    from apps.publishing import payments
    from apps.publishing import service as pub
    from apps.publishing.models import Order
    proj = get_object_or_404(
        Project.objects.filter(organization__in=organizations_for(request.user)), pk=pk
    )
    can_manage = proj.organization_id in _manageable_ids(request.user)
    website = getattr(proj, "website", None)

    if request.method == "POST":
        if not can_manage:
            messages.error(request, "Owner or admin required.")
            return redirect("dashboard:store", pk=pk)
        if website is None:
            website = pub.get_or_create_website(proj)
        action = request.POST.get("action")
        try:
            if action == "add_product":
                price = request.POST.get("price", "0").strip()
                cents = int(round(float(price) * 100))
                track = bool(request.POST.get("track_inventory"))
                stock = int(request.POST.get("stock") or 0)
                shop.create_product(website, name=(request.POST.get("name") or "").strip(),
                                    price_cents=cents,
                                    currency=(request.POST.get("currency") or "USD").strip().upper()[:3],
                                    description=(request.POST.get("description") or "").strip(),
                                    track_inventory=track, stock=stock, user=request.user)
                messages.success(request, "Product added.")
            elif action == "confirm_payment":
                order = Order.objects.filter(pk=request.POST.get("order", 0), website=website).first()
                if order:
                    shop.confirm_manual_payment(order, user=request.user)
                    messages.success(request, f"Order {order.reference} marked paid.")
            elif action == "cancel_order":
                order = Order.objects.filter(pk=request.POST.get("order", 0), website=website).first()
                if order:
                    shop.cancel_order(order, user=request.user)
                    messages.success(request, "Order cancelled.")
            elif action == "refund_order":
                order = Order.objects.filter(pk=request.POST.get("order", 0), website=website).first()
                if order:
                    shop.refund_order(order, user=request.user,
                                      reason=(request.POST.get("reason") or "").strip())
                    messages.success(request, f"Order {order.reference} refunded.")
            elif action == "generate_storefront":
                from apps.publishing import storefront
                try:
                    result = storefront.generate_storefront(website, user=request.user)
                    messages.success(request, f"Generated {result['pages']} storefront page(s). "
                                              "Publish to make the shop live.")
                except storefront.StorefrontError as exc:
                    messages.error(request, str(exc))
        except (shop.EcommerceError, ValueError) as exc:
            messages.error(request, str(exc))
        return redirect("dashboard:store", pk=pk)

    return render(request, "dashboard/store.html", {
        "active": "projects", "project": proj, "can_manage": can_manage,
        "website": website,
        "products": list(website.products.all()) if website else [],
        "orders": list(website.orders.prefetch_related("items")[:50]) if website else [],
        "providers": payments.provider_status(),
    })


@login_required
def content(request, pk):
    """Content management (spec §25): opt-in collections that generate real pages."""
    from apps.publishing import cms_service as cms
    from apps.publishing import service as pub
    from apps.publishing.models import ContentCollection
    proj = get_object_or_404(
        Project.objects.filter(organization__in=organizations_for(request.user)), pk=pk
    )
    can_manage = proj.organization_id in _manageable_ids(request.user)
    website = getattr(proj, "website", None)

    if request.method == "POST":
        if not can_manage:
            messages.error(request, "Owner or admin required.")
            return redirect("dashboard:content", pk=pk)
        if website is None:
            website = pub.get_or_create_website(proj)
        action = request.POST.get("action")
        try:
            if action == "add_collection":
                cms.create_collection(website, kind=request.POST.get("kind", "blog"),
                                      user=request.user)
                messages.success(request, "Collection added.")
            elif action == "add_item":
                coll = website.collections.filter(pk=request.POST.get("collection", 0)).first()
                if coll and (request.POST.get("title") or "").strip():
                    cms.add_item(coll, title=request.POST["title"].strip(),
                                 subtitle=request.POST.get("subtitle", "").strip(),
                                 body=request.POST.get("body", "").strip(), user=request.user)
                    messages.success(request, "Item added.")
                else:
                    messages.error(request, "A title is required.")
            elif action == "delete_item":
                from apps.publishing.models import ContentItem
                item = ContentItem.objects.filter(pk=request.POST.get("item", 0),
                                                  collection__website=website).first()
                if item:
                    item.delete()
                    messages.success(request, "Item deleted.")
            elif action == "generate":
                result = cms.generate(website, user=request.user)
                messages.success(request, f"Generated {result['pages']} content page(s). "
                                          "Publish to make them live.")
        except cms.CmsError as exc:
            messages.error(request, str(exc))
        return redirect("dashboard:content", pk=pk)

    collections = []
    if website:
        for c in website.collections.all():
            collections.append({"c": c, "items": list(c.items.all())})
    return render(request, "dashboard/content.html", {
        "active": "projects", "project": proj, "can_manage": can_manage,
        "website": website, "collections": collections, "kinds": ContentCollection.KINDS,
    })


@login_required
def assets(request, pk):
    """Asset manager for a website (spec §26): upload/resize/compress/replace/delete."""
    from apps.publishing import assets_service as assets_svc
    from apps.publishing import service as pub
    proj = get_object_or_404(
        Project.objects.filter(organization__in=organizations_for(request.user)), pk=pk
    )
    can_manage = proj.organization_id in _manageable_ids(request.user)
    website = getattr(proj, "website", None)

    if request.method == "POST":
        if not can_manage:
            messages.error(request, "Owner or admin required.")
            return redirect("dashboard:assets", pk=pk)
        if website is None:
            website = pub.get_or_create_website(proj)
        action = request.POST.get("action")
        try:
            if action == "upload":
                f = request.FILES.get("file")
                if not f:
                    messages.error(request, "Choose a file to upload.")
                else:
                    assets_svc.store_asset(website, filename=f.name, data=f.read(),
                                           content_type=f.content_type or "", user=request.user)
                    messages.success(request, "Asset uploaded.")
            else:
                asset = website.assets.filter(pk=request.POST.get("asset", 0)).first()
                if asset is None:
                    messages.error(request, "No such asset.")
                elif action == "resize":
                    assets_svc.resize_image(asset, width=int(request.POST.get("width") or 0),
                                            user=request.user)
                    messages.success(request, "Image resized.")
                elif action == "compress":
                    assets_svc.compress_image(asset, user=request.user)
                    messages.success(request, "Image compressed.")
                elif action == "replace":
                    f = request.FILES.get("file")
                    if f:
                        assets_svc.replace_asset(asset, data=f.read(), user=request.user)
                        messages.success(request, "Asset replaced.")
                elif action == "delete":
                    assets_svc.delete_asset(asset, user=request.user)
                    messages.success(request, "Asset deleted.")
        except (assets_svc.AssetError, ValueError) as exc:
            messages.error(request, str(exc))
        return redirect("dashboard:assets", pk=pk)

    rows = list(website.assets.all()) if website else []
    return render(request, "dashboard/assets.html", {
        "active": "projects", "project": proj, "can_manage": can_manage,
        "website": website, "assets": rows,
    })


@login_required
def asset_raw(request, pk, asset_id):
    """Serve an asset from the repo working tree for in-dashboard preview. Org-scoped."""
    import mimetypes
    from django.http import FileResponse, Http404
    from apps.publishing import assets_service as assets_svc
    from apps.publishing.models import Asset
    proj = get_object_or_404(
        Project.objects.filter(organization__in=organizations_for(request.user)), pk=pk
    )
    asset = get_object_or_404(Asset, pk=asset_id, website__project=proj)
    try:
        data = assets_svc.read_bytes(asset)
    except Exception:
        raise Http404("Asset file missing.")
    ctype = asset.content_type or mimetypes.guess_type(asset.path)[0] or "application/octet-stream"
    return FileResponse(iter([data]), content_type=ctype)


@login_required
def leads(request, pk):
    """Leads inbox — the CRM surface for a website's captured leads (spec §23)."""
    from apps.publishing.models import Lead
    proj = get_object_or_404(
        Project.objects.filter(organization__in=organizations_for(request.user)), pk=pk
    )
    can_manage = proj.organization_id in _manageable_ids(request.user)
    website = getattr(proj, "website", None)

    if request.method == "POST" and website and can_manage:
        lead = Lead.objects.filter(pk=request.POST.get("lead", 0), website=website).first()
        status = request.POST.get("status")
        if lead and status in dict(Lead.STATUS):
            lead.status = status
            lead.save(update_fields=["status"])
        return redirect("dashboard:leads", pk=pk)

    rows = list(website.leads.select_related("source_form")[:200]) if website else []
    status_counts = []
    if website:
        status_counts = [(label, website.leads.filter(status=s).count()) for s, label in Lead.STATUS]
    return render(request, "dashboard/leads.html", {
        "active": "projects", "project": proj, "can_manage": can_manage,
        "website": website, "leads": rows, "status_counts": status_counts, "statuses": Lead.STATUS,
    })


@login_required
def preview(request, pk):
    """Two-pane preview: chat (change requests) + a visual view of the app.

    Honest scope: this shows the app's real design (its screens/structure from the
    twin) and a sandboxed static render when the generated output is standalone
    HTML. A preview of the *running* application requires a deployment (a preview
    runner that executes the app in isolation) — surfaced as a Deploy link, not
    faked here.
    """
    proj = get_object_or_404(
        Project.objects.filter(organization__in=organizations_for(request.user)), pk=pk
    )
    can_manage = proj.organization_id in _manageable_ids(request.user)
    if request.method == "POST" and can_manage:
        from apps.preview_runner.runner import PreviewError, runner
        action = request.POST.get("action")
        if action == "start_preview":
            try:
                runner.start(proj)  # runs the app's server if declared, else serves files
                messages.success(request, "Live preview started.")
            except PreviewError as exc:
                messages.error(request, str(exc))
            return redirect("dashboard:preview", pk=pk)
        if action == "stop_preview":
            runner.stop(proj.id)
            messages.success(request, "Live preview stopped.")
            return redirect("dashboard:preview", pk=pk)
        desc = (request.POST.get("message") or "").strip()
        if desc:
            change = changes_service.create_change(proj, desc, request.user)
            changes_service.build_plan(change)
            if change.requires_approval:
                messages.success(request, "Planned — this change needs your approval.")
            else:
                changes_service.implement(change)
                messages.success(request, "Done — DevForge applied your change.")
        return redirect("dashboard:preview", pk=pk)

    ctx = ProjectContext(proj)
    screens = [
        {"name": e.title, "route": (e.data or {}).get("route", ""),
         "components": (e.data or {}).get("components", []),
         "platform": (e.data or {}).get("platform", "web")}
        for e in ctx.by_kind(ContextKind.SCREEN)
    ]
    # A truly standalone HTML file can be shown as a static snapshot (sandboxed,
    # scripts disabled). Skipped when it references external scripts/modules.
    from apps.repositories.service import repo_for_project
    preview_html = ""
    repo = repo_for_project(proj)
    if repo.is_initialized:
        files = repo.list_files()
        for cand in ("index.html", "public/index.html", "templates/index.html"):
            if cand in files:
                content = (repo.path / cand).read_text()
                if "<script" not in content.lower():
                    preview_html = content
                break
    from apps.preview_runner.runner import runner
    return render(request, "dashboard/preview.html", {
        "active": "projects", "project": proj, "can_manage": can_manage,
        "screens": screens, "preview_html": preview_html,
        "changes": proj.changes.all()[:8],
        "live": runner.get(proj.id) is not None,
    })


@login_required
def preview_live(request, pk, path=""):
    """Proxy the project's running static preview into the dashboard iframe."""
    import urllib.error
    import urllib.request

    proj = get_object_or_404(
        Project.objects.filter(organization__in=organizations_for(request.user)), pk=pk
    )
    from apps.preview_runner.runner import runner
    pv = runner.get(proj.id)
    if pv is None:
        raise Http404("No running preview for this project.")
    url = f"http://127.0.0.1:{pv.port}/{path}"
    if request.META.get("QUERY_STRING"):
        url += "?" + request.META["QUERY_STRING"]
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            body = resp.read()
            ctype = resp.headers.get_content_type() or "application/octet-stream"
    except urllib.error.URLError:
        raise Http404("The preview is not responding.")
    from django.http import HttpResponse
    return HttpResponse(body, content_type=ctype)


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
    elif action == "create_backup":
        from apps.backups.service import BackupError, create_backup
        try:
            b = create_backup(proj, label=request.POST.get("label") or "Snapshot",
                              created_by=request.user)
            messages.success(request, f"Backup “{b.label}” created.")
        except BackupError as exc:
            messages.error(request, str(exc))
    elif action == "restore_backup":
        from apps.backups.models import ProjectBackup
        from apps.backups.service import BackupError, restore_backup
        backup = ProjectBackup.objects.filter(
            pk=request.POST.get("backup", 0), project=proj).first()
        if backup is None:
            messages.error(request, "No such backup.")
        else:
            try:
                restore_backup(backup, actor=request.user)
                messages.success(request, f"Restored “{backup.label}”.")
            except BackupError as exc:
                messages.error(request, str(exc))


# --- engineering / project lists (real data) --------------------------------

# Customer-facing capabilities — outcomes only. The internal agent roster,
# capability model and orchestration are proprietary and never exposed here.
_CAPABILITIES = [
    ("Build", "Turn a brief into working, tested software in the stack you choose."),
    ("Understand", "Bring in an existing app and get a clear model of its architecture, APIs and data."),
    ("Improve", "Modernize, refactor and fix — described in plain language, implemented and verified."),
    ("Test", "Every change is compiled and its tests actually run before it's called done."),
    ("Secure", "Code is scanned for secrets, injection and unsafe patterns as part of each change."),
    ("Deploy", "Promote to dev and staging; production changes stay behind an approval gate."),
    ("Operate", "Track cost and activity per project, with rollback on any change."),
]


@login_required
def agents(request):
    return render(request, "dashboard/agents.html", {
        "active": "agents",
        "capabilities": [{"title": t, "blurb": b} for t, b in _CAPABILITIES],
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
    manageable = _manageable_ids(request.user)

    if request.method == "POST" and request.POST.get("action") == "generate_invoice":
        org = get_object_or_404(Organization, pk=request.POST.get("organization", 0))
        if org.id in manageable:
            from apps.credits.services import generate_invoice
            inv = generate_invoice(org)
            messages.success(
                request,
                f"Statement for {inv.period_start:%B %Y}: ${inv.subtotal_usd:.2f} "
                f"({inv.credits_used:.0f} credits).",
            )
        else:
            messages.error(request, "Owner or admin rights required.")
        return redirect("dashboard:usage")

    records = (
        UsageRecord.objects.filter(organization__in=orgs)
        .select_related("project").order_by("-created_at")[:100]
    )
    spend = sum((r.cost_usd for r in records), Decimal("0"))
    credits = sum((r.credits_charged for r in records), Decimal("0"))
    accounts = CreditAccount.objects.filter(organization__in=orgs)
    invoices = Invoice.objects.filter(organization__in=orgs).select_related("organization")
    return render(request, "dashboard/usage.html", {
        "active": "usage", "records": records, "spend": spend,
        "credits": credits, "accounts": accounts, "invoices": invoices,
        "manageable_orgs": [o for o in orgs if o.id in manageable],
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
