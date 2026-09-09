"""Built-in, code-defined global skills. These ship with DevForge; org/project skills
are authored on top of them in the DB. Each is a plain dict so builtins and DB rows
share one shape in the selector."""

BUILTIN_SKILLS = [
    {
        "slug": "ecommerce",
        "name": "E-commerce store",
        "keywords": ["shop", "store", "ecommerce", "e-commerce", "product", "cart", "checkout", "sell"],
        "body": ("This is an online store. Use DevForge's commerce engine (products, "
                 "cart, checkout, inventory, discounts, tax, shipping, orders) as the "
                 "source of truth — do not hand-write payment or stock logic. Include a "
                 "product listing, product pages, a cart and a checkout flow."),
    },
    {
        "slug": "crm",
        "name": "CRM",
        "keywords": ["crm", "lead", "contact", "pipeline", "deal", "sales"],
        "body": ("This is a CRM. Model contacts, leads and a simple pipeline with "
                 "stages; provide a dashboard of open leads and activity. Capture web "
                 "form submissions as leads."),
    },
    {
        "slug": "blog",
        "name": "Blog / content site",
        "keywords": ["blog", "article", "post", "news", "content"],
        "body": ("This is a content site. Use content collections (posts/articles) with "
                 "a listing page and per-post pages; keep clean headings and SEO metadata."),
    },
    {
        "slug": "booking",
        "name": "Booking / appointments",
        "keywords": ["booking", "appointment", "reservation", "schedule", "calendar"],
        "body": ("This app takes bookings. Model services/slots and a booking form that "
                 "captures the customer, date/time and confirmation."),
    },
    {
        "slug": "saas",
        "name": "SaaS app",
        "keywords": ["saas", "subscription", "multi-tenant", "workspace", "dashboard"],
        "body": ("This is a SaaS app. Use organizations/teams with roles, per-tenant "
                 "isolation, an authenticated dashboard and subscription-ready billing hooks."),
    },
]


def builtin_as_shape(b: dict) -> dict:
    return {"name": b["name"], "slug": b["slug"], "keywords": b["keywords"],
            "body": b["body"], "source": "builtin"}
