"""Website Creation & Publishing — data model (spec §5, §17, §41, §42).

Phase 1 (spec §51): a project's website facet, versioned publishes, a working
DevForge URL, health, and rollback. Reuses existing DevForge infrastructure
(Project/Organization/Repository/Audit) rather than duplicating it (spec §1).

HONESTY (spec §50): a PublishVersion is only LIVE when its build was actually
snapshotted and is served by DevForge. Public custom-domain + SSL hosting needs
cloud/DNS infra that isn't configured here; that stays a Phase-2 gated path and is
never shown as active until it is.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class PublishState(models.TextChoices):
    # Customer-facing states (spec §42) — no internal agent topology.
    DRAFT = "draft", "Draft"
    BUILDING = "building", "Building"
    TESTING = "testing", "Testing"
    READY = "ready", "Ready to publish"
    PUBLISHING = "publishing", "Publishing"
    LIVE = "live", "Live"
    NEEDS_ATTENTION = "needs_attention", "Needs attention"
    FAILED = "failed", "Failed"


class Website(models.Model):
    """A project's published-website facet (spec §5 Digital Twin surface)."""

    project = models.OneToOneField(
        "projects.Project", on_delete=models.CASCADE, related_name="website"
    )
    subdomain = models.SlugField(max_length=63, unique=True)
    site_type = models.CharField(max_length=32, default="business")   # inferred; not forced
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.subdomain} ({self.project.name})"

    @property
    def current(self):
        return self.versions.filter(is_current=True).first()


class PublishVersion(models.Model):
    """One versioned publish of a website to an environment (spec §17)."""

    website = models.ForeignKey(Website, on_delete=models.CASCADE, related_name="versions")
    version = models.CharField(max_length=32)                 # v1.0.0, v1.0.1, …
    environment = models.CharField(max_length=20, default="production")
    host = models.CharField(max_length=32, default="devforge_local")
    state = models.CharField(max_length=20, choices=PublishState.choices, default=PublishState.DRAFT)
    url = models.CharField(max_length=1024, blank=True)       # working DevForge URL when live
    artifact_dir = models.CharField(max_length=1024, blank=True)  # snapshot served for this version
    commit = models.CharField(max_length=40, blank=True)
    health = models.CharField(max_length=16, default="unknown")   # unknown / healthy / down
    health_detail = models.CharField(max_length=255, blank=True)
    readiness = models.PositiveSmallIntegerField(default=0)
    is_current = models.BooleanField(default=False)
    log = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="publish_versions",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.website.subdomain} {self.version} ({self.state})"


class CustomDomain(models.Model):
    """A custom domain a customer wants to point at their DevForge site (spec §19).

    HONESTY: `verification_status` becomes 'verified' only when a real DNS lookup
    finds the token; `ssl_status` becomes 'active' only when a real certificate is
    installed. Neither is ever set on a timer or faked (spec §50)."""

    VERIFY_PENDING = "pending"
    VERIFY_VERIFIED = "verified"
    VERIFY_FAILED = "failed"

    SSL_NONE = "none"
    SSL_PENDING = "pending"
    SSL_ACTIVE = "active"
    SSL_FAILED = "failed"

    website = models.ForeignKey(Website, on_delete=models.CASCADE, related_name="domains")
    hostname = models.CharField(max_length=253, unique=True)
    provider = models.CharField(max_length=32, default="manual")
    verification_token = models.CharField(max_length=64)
    required_records = models.JSONField(default=list, blank=True)
    verification_status = models.CharField(max_length=16, default=VERIFY_PENDING)
    ssl_status = models.CharField(max_length=16, default=SSL_NONE)
    detail = models.CharField(max_length=500, blank=True)
    last_checked = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="custom_domains",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.hostname} ({self.verification_status})"

    @property
    def is_verified(self) -> bool:
        return self.verification_status == self.VERIFY_VERIFIED

    @property
    def is_live(self) -> bool:
        # Only truly live when verified AND a real certificate is active.
        return self.is_verified and self.ssl_status == self.SSL_ACTIVE


class SeoConfig(models.Model):
    """Site-level SEO settings (spec §27). AI may draft copy; the customer edits it,
    and nothing is applied to the actual pages without an explicit apply step."""

    website = models.OneToOneField(Website, on_delete=models.CASCADE, related_name="seo")
    title_suffix = models.CharField(max_length=120, blank=True)   # e.g. " · Acme"
    default_description = models.CharField(max_length=320, blank=True)
    og_image = models.CharField(max_length=1024, blank=True)
    robots_allow = models.BooleanField(default=True)              # allow indexing
    sitemap_enabled = models.BooleanField(default=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"SEO for {self.website.subdomain}"


class PageSeo(models.Model):
    """Per-page SEO metadata draft (spec §27)."""

    config = models.ForeignKey(SeoConfig, on_delete=models.CASCADE, related_name="pages")
    path = models.CharField(max_length=512)                       # repo-relative html file
    title = models.CharField(max_length=200, blank=True)
    description = models.CharField(max_length=320, blank=True)
    og_title = models.CharField(max_length=200, blank=True)
    og_description = models.CharField(max_length=320, blank=True)
    canonical = models.CharField(max_length=1024, blank=True)
    ai_generated = models.BooleanField(default=False)
    approved = models.BooleanField(default=False)
    applied = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["path"]
        constraints = [
            models.UniqueConstraint(fields=["config", "path"], name="uniq_pageseo_path")
        ]

    def __str__(self):
        return f"{self.path} SEO"


class Form(models.Model):
    """A form on a customer's website (spec §23). Submissions are validated, stored,
    emailed, and turned into CRM leads."""

    KINDS = [
        ("contact", "Contact"), ("lead", "Lead"), ("quote", "Quotation request"),
        ("newsletter", "Newsletter"), ("booking", "Booking"), ("custom", "Custom"),
    ]

    website = models.ForeignKey(Website, on_delete=models.CASCADE, related_name="forms")
    slug = models.SlugField(max_length=64)
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=20, choices=KINDS, default="contact")
    fields = models.JSONField(default=list)   # [{name,label,type,required}]
    notify_email = models.EmailField(blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["website", "slug"], name="uniq_form_slug")
        ]

    def __str__(self):
        return f"{self.name} ({self.website.subdomain})"


class FormSubmission(models.Model):
    """One raw submission of a form (spec §23)."""

    form = models.ForeignKey(Form, on_delete=models.CASCADE, related_name="submissions")
    data = models.JSONField(default=dict)
    is_spam = models.BooleanField(default=False)
    email_notified = models.BooleanField(default=False)   # honest: only true if actually sent
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"submission of {self.form_id} @ {self.created_at:%Y-%m-%d}"


class Lead(models.Model):
    """A CRM lead captured from a website form (spec §23). This is the CRM surface —
    where leads live and are worked — not a disconnected side store."""

    STATUS = [("new", "New"), ("contacted", "Contacted"), ("qualified", "Qualified"),
              ("won", "Won"), ("lost", "Lost")]

    website = models.ForeignKey(Website, on_delete=models.CASCADE, related_name="leads")
    source_form = models.ForeignKey(Form, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="leads")
    submission = models.OneToOneField(FormSubmission, on_delete=models.CASCADE,
                                      null=True, blank=True, related_name="lead")
    name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=64, blank=True)
    message = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=STATUS, default="new")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name or self.email or 'Lead'} ({self.status})"


class Asset(models.Model):
    """A media asset for a website (spec §26). Stored inside the project's repo under
    assets/ so it publishes and is served with the site. Uploads are validated and
    filenames sanitized (file-upload safety, spec §31)."""

    KIND_IMAGE = "image"
    KIND_VIDEO = "video"
    KIND_DOCUMENT = "document"
    KIND_FONT = "font"
    KIND_ICON = "icon"

    website = models.ForeignKey(Website, on_delete=models.CASCADE, related_name="assets")
    path = models.CharField(max_length=512)          # repo-relative, e.g. assets/logo.png
    original_name = models.CharField(max_length=255)
    kind = models.CharField(max_length=16, default=KIND_IMAGE)
    content_type = models.CharField(max_length=128, blank=True)
    size = models.PositiveIntegerField(default=0)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="uploaded_assets",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["website", "path"], name="uniq_asset_path")
        ]

    def __str__(self):
        return f"{self.path} ({self.website.subdomain})"

    @property
    def is_image(self) -> bool:
        return self.kind in (self.KIND_IMAGE, self.KIND_ICON)


class PageView(models.Model):
    """One real page view of a published site (spec §28).

    PRIVACY: no raw IP or PII is stored. `session_key` is a one-way daily-salted hash
    of IP+User-Agent, so sessions can be counted without identifying or tracking a
    person across days. Do-Not-Track is honored (no row is written). Referrer is
    reduced to its host only."""

    website = models.ForeignKey(Website, on_delete=models.CASCADE, related_name="page_views")
    path = models.CharField(max_length=512)
    referrer_host = models.CharField(max_length=255, blank=True)
    device = models.CharField(max_length=16, default="desktop")   # desktop / mobile / bot
    session_key = models.CharField(max_length=32)
    day = models.DateField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["website", "day"])]

    def __str__(self):
        return f"{self.website.subdomain}{self.path} @ {self.day}"


class HealthCheck(models.Model):
    """One recorded health probe of a published site (spec §36).

    HONEST SCOPE: this probes the site DevForge actually serves — is the current
    published snapshot present and readable, and how long did serving it take. Remote
    server metrics (CPU/memory/traffic of a box DevForge doesn't run) are not
    monitored here and are shown as such, never faked."""

    website = models.ForeignKey(Website, on_delete=models.CASCADE, related_name="health_checks")
    version = models.ForeignKey(PublishVersion, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="health_checks")
    status = models.CharField(max_length=8, default="up")   # up / down
    detail = models.CharField(max_length=255, blank=True)
    response_ms = models.PositiveIntegerField(default=0)
    checked_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-checked_at"]
        indexes = [models.Index(fields=["website", "checked_at"])]

    def __str__(self):
        return f"{self.website.subdomain} {self.status} @ {self.checked_at:%Y-%m-%d %H:%M}"


class ContentCollection(models.Model):
    """An editable content collection for a website (spec §25). Opt-in — a CMS is
    only added to sites that need one, never forced onto a simple static site."""

    KINDS = [
        ("blog", "Blog"), ("article", "Articles"), ("faq", "FAQs"),
        ("service", "Services"), ("team", "Team"), ("testimonial", "Testimonials"),
        ("product", "Products"), ("project", "Projects"), ("page", "Pages"),
    ]

    website = models.ForeignKey(Website, on_delete=models.CASCADE, related_name="collections")
    slug = models.SlugField(max_length=64)
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=20, choices=KINDS, default="blog")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["website", "slug"], name="uniq_collection_slug")
        ]

    def __str__(self):
        return f"{self.name} ({self.website.subdomain})"


class ContentItem(models.Model):
    """One entry in a collection (spec §25)."""

    collection = models.ForeignKey(ContentCollection, on_delete=models.CASCADE, related_name="items")
    slug = models.SlugField(max_length=80)
    title = models.CharField(max_length=200)
    subtitle = models.CharField(max_length=255, blank=True)   # role, author, tagline…
    body = models.TextField(blank=True)
    image = models.CharField(max_length=1024, blank=True)     # asset path/url, optional
    published = models.BooleanField(default=True)
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["collection", "slug"], name="uniq_item_slug")
        ]

    def __str__(self):
        return self.title


class AcmeChallenge(models.Model):
    """An ACME HTTP-01 challenge DevForge serves for SSL issuance (spec §22).

    During issuance an ACME client (Let's Encrypt et al.) stores a token + key
    authorization here; the CA then fetches /.well-known/acme-challenge/<token> and
    must get the key authorization back. Serving the challenge is real and testable;
    the CA-client conversation itself needs network + an ACME library, so it stays
    gated — but the piece the edge must provide is built."""

    domain = models.ForeignKey(CustomDomain, on_delete=models.CASCADE, related_name="acme_challenges")
    token = models.CharField(max_length=255, unique=True)
    key_authorization = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"acme-challenge {self.token[:12]}… for {self.domain.hostname}"


class Product(models.Model):
    """A product a customer's website sells (spec §32). Prices are stored in integer
    minor units (cents) to avoid float rounding."""

    website = models.ForeignKey(Website, on_delete=models.CASCADE, related_name="products")
    slug = models.SlugField(max_length=80)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    price_cents = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=3, default="USD")
    active = models.BooleanField(default=True)
    track_inventory = models.BooleanField(default=False)
    stock = models.IntegerField(default=0)   # meaningful only when track_inventory
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["website", "slug"], name="uniq_product_slug")
        ]

    def __str__(self):
        return f"{self.name} ({self.price_display})"

    @property
    def price_display(self) -> str:
        return f"{self.currency} {self.price_cents / 100:.2f}"

    @property
    def in_stock(self) -> bool:
        return (not self.track_inventory) or self.stock > 0

    @property
    def price_units(self) -> str:
        return f"{self.price_cents / 100:.2f}"


class DiscountCode(models.Model):
    """A discount code a store honors (spec §32). Percentage or fixed amount, with
    optional expiry, usage cap and minimum order. Enforced server-side at checkout —
    the discount is computed from real values, never trusted from the client."""

    PERCENT = "percent"
    FIXED = "fixed"

    website = models.ForeignKey(Website, on_delete=models.CASCADE, related_name="discount_codes")
    code = models.CharField(max_length=40)                 # stored uppercased
    kind = models.CharField(max_length=8, default=PERCENT)
    percent_off = models.PositiveSmallIntegerField(default=0)   # 1..100 for percent
    amount_off_cents = models.PositiveIntegerField(default=0)   # for fixed
    currency = models.CharField(max_length=3, default="USD")    # fixed must match order
    min_subtotal_cents = models.PositiveIntegerField(default=0)
    max_uses = models.PositiveIntegerField(default=0)      # 0 = unlimited
    used_count = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(fields=["website", "code"], name="uniq_discount_code")
        ]

    def __str__(self):
        return self.code

    @property
    def summary(self) -> str:
        return f"{self.percent_off}% off" if self.kind == self.PERCENT \
            else f"{self.currency} {self.amount_off_cents / 100:.2f} off"


class ShippingRate(models.Model):
    """A delivery option a store offers (spec §32). Flat price, with an optional
    free-over threshold. Applied to physical orders at checkout; the cost is added to
    the order total exactly (deterministic)."""

    website = models.ForeignKey(Website, on_delete=models.CASCADE, related_name="shipping_rates")
    name = models.CharField(max_length=120)             # "Standard", "Express", "Pickup"
    price_cents = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=3, default="USD")
    free_over_cents = models.PositiveIntegerField(default=0)   # 0 = no free threshold
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["price_cents", "name"]

    def __str__(self):
        return f"{self.name} ({self.currency} {self.price_cents / 100:.2f})"

    def cost_for(self, subtotal_cents: int) -> int:
        if self.free_over_cents and subtotal_cents >= self.free_over_cents:
            return 0
        return self.price_cents

    @property
    def price_display(self) -> str:
        base = f"{self.currency} {self.price_cents / 100:.2f}"
        if self.free_over_cents:
            base += f" (free over {self.currency} {self.free_over_cents / 100:.2f})"
        return base


class Order(models.Model):
    """A customer order (spec §32). Status reflects the REAL payment state — it only
    becomes 'paid' when a payment actually succeeds (a gateway confirmation or a
    merchant confirming a manual payment), never optimistically."""

    STATUS = [
        ("pending", "Pending"), ("awaiting_payment", "Awaiting payment"),
        ("paid", "Paid"), ("failed", "Failed"),
        ("refunded", "Refunded"), ("cancelled", "Cancelled"),
    ]

    website = models.ForeignKey(Website, on_delete=models.CASCADE, related_name="orders")
    reference = models.CharField(max_length=32, unique=True)
    customer_name = models.CharField(max_length=255, blank=True)
    customer_email = models.EmailField(blank=True)
    subtotal_cents = models.PositiveIntegerField(default=0)   # before discount
    discount_cents = models.PositiveIntegerField(default=0)
    shipping_cents = models.PositiveIntegerField(default=0)
    total_cents = models.PositiveIntegerField(default=0)      # what is actually charged
    discount_code = models.ForeignKey(
        "publishing.DiscountCode", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="orders",
    )
    shipping_rate = models.ForeignKey(
        "publishing.ShippingRate", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="orders",
    )
    shipping_address = models.TextField(blank=True)
    currency = models.CharField(max_length=3, default="USD")
    status = models.CharField(max_length=20, choices=STATUS, default="pending")
    provider = models.CharField(max_length=32, blank=True)
    # Honest email state: only True when an email actually sent (buyer gave an address).
    confirmation_sent = models.BooleanField(default=False)
    receipt_sent = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.reference} ({self.status})"

    @property
    def total_display(self) -> str:
        return f"{self.currency} {self.total_cents / 100:.2f}"

    @property
    def subtotal_display(self) -> str:
        return f"{self.currency} {self.subtotal_cents / 100:.2f}"

    @property
    def discount_display(self) -> str:
        return f"{self.currency} {self.discount_cents / 100:.2f}"

    @property
    def shipping_display(self) -> str:
        return f"{self.currency} {self.shipping_cents / 100:.2f}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="order_items")
    name = models.CharField(max_length=200)
    unit_price_cents = models.PositiveIntegerField(default=0)
    quantity = models.PositiveIntegerField(default=1)

    @property
    def line_total_cents(self) -> int:
        return self.unit_price_cents * self.quantity

    def __str__(self):
        return f"{self.quantity} × {self.name}"


class Payment(models.Model):
    """A payment attempt against an order (spec §24, §32). `succeeded` is set only on a
    real confirmation — a gateway callback or a merchant confirming a manual payment.
    Card/gateway processing is gated on credentials + a verified integration; nothing
    here fabricates a successful charge."""

    STATUS = [("pending", "Pending"), ("succeeded", "Succeeded"),
              ("failed", "Failed"), ("refunded", "Refunded")]

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="payments")
    provider = models.CharField(max_length=32)
    method = models.CharField(max_length=32, blank=True)     # manual / card / …
    amount_cents = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=3, default="USD")
    status = models.CharField(max_length=16, choices=STATUS, default="pending")
    provider_ref = models.CharField(max_length=255, blank=True)
    detail = models.CharField(max_length=500, blank=True)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="confirmed_payments",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.provider} {self.amount_cents / 100:.2f} ({self.status})"


class PublishCheck(models.Model):
    """One publish-readiness check result (spec §12, §41)."""

    version = models.ForeignKey(PublishVersion, on_delete=models.CASCADE, related_name="checks")
    key = models.CharField(max_length=32)
    label = models.CharField(max_length=128)
    status = models.CharField(max_length=16)     # ok / warn / fail / manual
    detail = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.key}={self.status}"
