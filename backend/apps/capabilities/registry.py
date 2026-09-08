"""The DevForge Capability Platform — the building blocks an app can be given.

A customer describes an outcome ("a CRM for my construction company"); DevForge
infers the capabilities that outcome needs (auth, database, email, …) instead of
making them configure each one. This registry is the catalogue, grouped, with an
HONEST status per capability:

  - "available"  : DevForge genuinely provides or builds this today.
  - "planned"    : on the roadmap; not offered yet.

Status is the guardrail behind the product principle "market only what we
actually provide" — marketing and inference must never present a planned
capability as if it were live.
"""
from __future__ import annotations

from dataclasses import dataclass

AVAILABLE = "available"
PLANNED = "planned"


@dataclass(frozen=True)
class Capability:
    id: str
    name: str
    group: str
    status: str
    description: str

    @property
    def is_available(self) -> bool:
        return self.status == AVAILABLE


# Honest statuses as of today: authentication/users/roles, relational database,
# APIs, transactional email (notifications), basic search, dashboards, code
# review + security scan, deploy/preview, export, and Git connect are real.
# Payments, storage, SMS, jobs, analytics, monitoring, multi-currency, tax, SSO,
# and most third-party integrations are on the roadmap.
_CATALOG = [
    # Application
    Capability("auth", "Authentication", "Application", AVAILABLE, "Sign-up, login, password reset."),
    Capability("users", "Users", "Application", AVAILABLE, "User accounts and profiles."),
    Capability("roles", "Roles & permissions", "Application", AVAILABLE, "Org roles and access control."),
    Capability("database", "Database", "Application", AVAILABLE, "Structured data and relationships."),
    Capability("api", "APIs", "Application", AVAILABLE, "HTTP APIs for your data."),
    Capability("search", "Search", "Application", AVAILABLE, "Find records across your app."),
    Capability("dashboard", "Dashboards", "Application", AVAILABLE, "Metrics and overviews."),
    Capability("email", "Email", "Application", AVAILABLE, "Transactional and notification email."),
    Capability("files", "File storage", "Application", PLANNED, "Uploads, downloads and previews."),
    Capability("sms", "SMS", "Application", PLANNED, "Text-message notifications."),
    Capability("jobs", "Background jobs", "Application", PLANNED, "Async and scheduled work."),
    # Business
    Capability("crm", "CRM", "Business", AVAILABLE, "Contacts, leads, deals, activities."),
    Capability("payments", "Payments", "Business", PLANNED, "Checkout and payment processing."),
    Capability("subscriptions", "Subscriptions", "Business", PLANNED, "Recurring billing."),
    Capability("invoicing", "Invoicing", "Business", PLANNED, "Invoices and receipts."),
    Capability("tax", "Tax", "Business", PLANNED, "VAT/sales-tax on documents."),
    Capability("currency", "Multi-currency", "Business", PLANNED, "Prices and reporting per currency."),
    Capability("ecommerce", "E-commerce", "Business", AVAILABLE, "Products, cart, orders."),
    # Growth
    Capability("analytics", "Analytics", "Growth", PLANNED, "Usage, conversions and revenue."),
    Capability("seo", "SEO", "Growth", PLANNED, "Discoverability for public pages."),
    Capability("forms", "Forms", "Growth", AVAILABLE, "Capture input and leads."),
    Capability("campaigns", "Email campaigns", "Growth", PLANNED, "Marketing email sends."),
    # Infrastructure
    Capability("hosting", "Hosting", "Infrastructure", AVAILABLE, "Preview and deploy your app."),
    Capability("domains", "Custom domains", "Infrastructure", PLANNED, "Your own domain + SSL."),
    Capability("backups", "Backups", "Infrastructure", PLANNED, "Scheduled data backups."),
    Capability("environments", "Environments", "Infrastructure", AVAILABLE, "Dev/staging workspaces."),
    Capability("monitoring", "Monitoring", "Infrastructure", PLANNED, "Health, errors and uptime."),
    # Cross-cutting
    Capability("security", "Security", "Protect", AVAILABLE, "Secret + injection scanning on every change."),
    Capability("audit", "Audit log", "Protect", AVAILABLE, "A record of who changed what."),
    Capability("export", "Export / no lock-in", "Protect", AVAILABLE, "Download your code anytime."),
    Capability("ai", "AI features", "Growth", PLANNED, "Chatbots and document Q&A in your app."),
    # Integrations
    Capability("git", "GitHub / GitLab", "Integrations", AVAILABLE, "Import and connect repositories."),
    Capability("google", "Google Workspace", "Integrations", PLANNED, "Sign-in and data."),
    Capability("slack", "Slack", "Integrations", PLANNED, "Notifications and actions."),
    Capability("whatsapp", "WhatsApp", "Integrations", PLANNED, "Messaging."),
    Capability("stripe", "Stripe", "Integrations", PLANNED, "Card payments."),
    Capability("payfast", "PayFast", "Integrations", PLANNED, "South African payments."),
]

_BY_ID = {c.id: c for c in _CATALOG}
_GROUP_ORDER = ["Application", "Business", "Growth", "Infrastructure", "Protect", "Integrations"]


def get(capability_id: str) -> Capability | None:
    return _BY_ID.get(capability_id)


def all_capabilities() -> list[Capability]:
    return list(_CATALOG)


def by_group() -> list[tuple[str, list[Capability]]]:
    groups: dict[str, list[Capability]] = {}
    for c in _CATALOG:
        groups.setdefault(c.group, []).append(c)
    return [(g, groups[g]) for g in _GROUP_ORDER if g in groups]
