"""Public marketing site + self-serve sign-up.

All pages are public (no login). Content is real product description; live data
(the agent roster, supported stacks, pricing tiers) comes from the platform, so
nothing here is fabricated — no fake customers, logos, or metrics.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import login
from django.shortcuts import redirect, render

from apps.credits.services import ensure_account, plans
from apps.marketing.models import ContactMessage
from apps.organizations.models import Organization, Role
from apps.technology.registry import Category
from apps.technology.registry import registry as tech_registry

# Public messaging shows OUTCOMES across the software lifecycle — never the
# internal machinery (no agent names, orchestration, routing, permissions, or
# model-selection logic). That topology is proprietary and stays behind auth.
_PILLARS = [
    ("Build", "Turn ideas into working software in the technology stack you choose."),
    ("Improve", "Analyze existing software, then fix, refactor, secure, and extend it."),
    ("Deploy", "Ship to dev and staging automatically; production stays behind an approval gate."),
    ("Operate", "Monitor, track cost per project, and keep improving — with a full audit trail."),
]

_CAPABILITIES = [
    ("Build", "Turn ideas into working software.",
     "Describe what you need and get designed, generated, and tested software you can run and export."),
    ("Understand", "Analyze existing applications and codebases.",
     "Bring in a repository and get a clear picture of its architecture, APIs, and data."),
    ("Improve", "Find and resolve technical, security and performance issues.",
     "Modernize, refactor and harden the software you already have."),
    ("Test", "Validate software automatically.",
     "Generated projects come with tests that actually run."),
    ("Deploy", "Move applications into production environments.",
     "Promote to dev and staging; production changes stay behind an approval gate."),
    ("Operate", "Monitor and continuously improve running software.",
     "Track usage and cost per project, with a full audit trail."),
]


_BUILD_CATEGORIES = [
    ("Business applications", ["CRM", "ERP", "Operations software", "HR systems", "Finance systems"]),
    ("Customer products", ["SaaS", "Marketplaces", "Booking systems", "E-commerce", "Customer portals"]),
    ("Websites", ["Business websites", "Landing pages", "Marketing sites", "Directories"]),
    ("Internal tools", ["Dashboards", "Approval systems", "Workflow tools", "Reporting"]),
    ("Developer products", ["APIs", "Backend systems", "Data applications", "Developer tools"]),
]
_EXAMPLES = [
    ("CRM", "Build a CRM with contacts, companies, leads, deals and a sales dashboard."),
    ("SaaS", "Build a SaaS platform where teams sign up, manage members and subscribe."),
    ("Website", "Build a professional website for my business with services and contact pages."),
    ("E-commerce", "Build an online store with a product catalog, cart, checkout and orders."),
    ("Customer Portal", "Build a portal where clients log in, submit requests and track status."),
    ("Internal Tool", "Build an internal tool to manage tasks, approvals and reports."),
]
_IMPROVE_EXAMPLES = [
    "Add WhatsApp support.", "Fix the checkout.", "Make the dashboard faster.",
    "Add employee leave management.", "Add PayFast payments.",
    "Redesign the customer portal.", "Modernize this old application.",
]


def _base_context():
    return {
        "pillars": _PILLARS,
        "capabilities": _CAPABILITIES,
        "languages": tech_registry.by_category(Category.LANGUAGE),
        "frameworks": tech_registry.by_category(Category.FRAMEWORK),
    }


def home(request):
    ctx = _base_context()
    ctx.update({
        "build_categories": _BUILD_CATEGORIES,
        "examples": _EXAMPLES,
        "improve_examples": _IMPROVE_EXAMPLES,
    })
    return render(request, "marketing/home.html", ctx)


def platform(request):
    return render(request, "marketing/platform.html", _base_context())


def how_it_works(request):
    # Outcome steps only — no agent names or internal routing.
    steps = [
        ("Describe", "Tell DevForge what you want to build, in plain language."),
        ("Plan", "Your intent becomes clear requirements and a technical plan — and you choose the technology stack."),
        ("Build", "Your application is generated in the chosen stack."),
        ("Validate", "Tests run automatically to check it works."),
        ("Deploy", "Ship to development and staging; production changes need your approval."),
        ("Operate", "Monitor, track cost, and keep improving."),
    ]
    return render(request, "marketing/how_it_works.html", {**_base_context(), "steps": steps})


def capabilities(request):
    return render(request, "marketing/capabilities.html", _base_context())


def pricing(request):
    tiers = [
        {"name": "Free", "price": "$0", "credits": plans().get("free", 0),
         "blurb": "Explore DevForge.",
         "features": ["Build projects", "Limited AI usage", "Preview", "Export your code anytime"]},
        {"name": "Builder", "price": "$29", "credits": plans().get("pro", 0),
         "blurb": "For serious builders.",
         "features": ["More AI credits", "More projects", "Deployment", "Git integration", "Custom domain"],
         "highlight": True},
        {"name": "Pro", "price": "$99", "credits": plans().get("business", 0),
         "blurb": "For businesses.",
         "features": ["Higher AI allowance", "Improve existing software", "Team collaboration",
                      "Monitoring", "More deployment capacity"]},
        {"name": "Business", "price": "Custom", "credits": None,
         "blurb": "For growing teams.",
         "features": ["Team management", "Security & audit logs", "Private deployments",
                      "Advanced controls", "Priority support"]},
    ]
    return render(request, "marketing/pricing.html", {**_base_context(), "tiers": tiers})


def about(request):
    return render(request, "marketing/about.html", _base_context())


def contact(request):
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        email = (request.POST.get("email") or "").strip()
        body = (request.POST.get("message") or "").strip()
        if name and email and body:
            ContactMessage.objects.create(
                name=name, email=email,
                company=(request.POST.get("company") or "").strip(), message=body,
            )
            messages.success(request, "Thanks — we’ve received your message and will be in touch.")
            return redirect("marketing:contact")
        messages.error(request, "Please provide your name, email, and a message.")
    return render(request, "marketing/contact.html", _base_context())


def signup(request):
    idea = (request.GET.get("idea") or request.POST.get("idea") or "").strip()
    if request.user.is_authenticated:
        if idea:
            request.session["build_idea"] = idea[:2000]
        return redirect("dashboard:home")
    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        password = request.POST.get("password") or ""
        full_name = (request.POST.get("full_name") or "").strip()
        org_name = (request.POST.get("org_name") or "").strip()
        from apps.accounts.models import User

        if not email or len(password) < 8:
            messages.error(request, "Enter an email and a password of at least 8 characters.")
        elif User.objects.filter(email__iexact=email).exists():
            messages.error(request, "An account with that email already exists. Try logging in.")
        else:
            user = User.objects.create_user(email=email, password=password, full_name=full_name)
            org = Organization.objects.create(
                name=org_name or f"{full_name or email.split('@')[0]}'s workspace",
                created_by=user,
            )
            org.add_member(user, role=Role.OWNER)
            ensure_account(org, plan="free")  # start with free-tier credits
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            idea = (request.POST.get("idea") or "").strip()
            if idea:
                request.session["build_idea"] = idea[:2000]  # carried into the builder
            return redirect("dashboard:home")
    ctx = _base_context()
    ctx["idea"] = (request.GET.get("idea") or request.POST.get("idea") or "").strip()
    return render(request, "marketing/signup.html", ctx)
