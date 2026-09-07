"""Public marketing site + self-serve sign-up.

All pages are public (no login). Content is real product description; live data
(the agent roster, supported stacks, pricing tiers) comes from the platform, so
nothing here is fabricated — no fake customers, logos, or metrics.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import login
from django.shortcuts import redirect, render

from apps.agents.definitions import registry as agent_registry
from apps.credits.services import ensure_account, plans
from apps.marketing.models import ContactMessage
from apps.organizations.models import Organization, Role
from apps.technology.registry import Category
from apps.technology.registry import registry as tech_registry
from apps.technology.stacks import all_stacks

# The four lifecycle pillars shown across the site.
_PILLARS = [
    ("Build", "Describe software; specialist agents design, implement, test, and review it in the stack you choose."),
    ("Improve", "Import an existing codebase, understand it, then fix, refactor, secure, and extend it."),
    ("Deploy", "Ship to dev and staging automatically; production stays behind an approval gate."),
    ("Operate", "Monitor, track cost per project, and scale — with a full audit trail."),
]


def _runnable_stack_ids():
    return {s.id for s in all_stacks() if s.is_runnable()}


def _base_context():
    langs = tech_registry.by_category(Category.LANGUAGE)
    frameworks = tech_registry.by_category(Category.FRAMEWORK)
    return {
        "pillars": _PILLARS,
        "agents": agent_registry.all(),
        "languages": langs,
        "frameworks": frameworks,
        "runnable_ids": _runnable_stack_ids(),
    }


def home(request):
    return render(request, "marketing/home.html", _base_context())


def platform(request):
    return render(request, "marketing/platform.html", _base_context())


def how_it_works(request):
    steps = [
        ("Describe", "Tell DevForge what to build, in plain language."),
        ("Requirements", "The Requirements Agent turns intent into testable requirements."),
        ("Architecture", "The Architect designs components and proposes a technology stack you select."),
        ("Implement", "Backend, Frontend, Database and Mobile agents build in the chosen stack."),
        ("Test & Review", "The Testing agent runs real tests; Code Review checks the design."),
        ("Deploy & Operate", "Ship to dev/staging; production needs approval. Then monitor and scale."),
    ]
    return render(request, "marketing/how_it_works.html", {**_base_context(), "steps": steps})


def agents(request):
    return render(request, "marketing/agents.html", _base_context())


def pricing(request):
    tiers = [
        {"name": "Free", "price": "$0", "credits": plans().get("free", 0),
         "blurb": "Explore DevForge and build your first project.",
         "features": ["1 organization", "Community support", "Export your code anytime"]},
        {"name": "Pro", "price": "$49", "credits": plans().get("pro", 0),
         "blurb": "For individual builders shipping real software.",
         "features": ["Unlimited projects", "All runnable stacks", "Priority agents"], "highlight": True},
        {"name": "Business", "price": "$199", "credits": plans().get("business", 0),
         "blurb": "For teams building and operating products.",
         "features": ["Team members & roles", "Deployments & environments", "Usage analytics"]},
        {"name": "Enterprise", "price": "Custom", "credits": None,
         "blurb": "Private deployment, SSO, data residency, and support.",
         "features": ["SSO / SAML", "Private models & networking", "Dedicated support"]},
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
    if request.user.is_authenticated:
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
            return redirect("dashboard:home")
    return render(request, "marketing/signup.html", _base_context())
