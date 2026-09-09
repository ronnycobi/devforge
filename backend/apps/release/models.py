"""Mobile Release & App Store Platform — data model (spec §14, §21, §22, §36).

Provider-independent by design: ONE MobileApplication can target Google Play,
Apple and Huawei at once (spec §40) through per-store StoreApplication rows, and
one store being blocked never blocks another.

SECURITY (spec §1, §26, §27): no model here stores a Google/Apple/Huawei password
or a raw secret. Store and signing credentials are held only as opaque *references*
(a handle into a vault) plus their type/scopes/status. Agents and the frontend
never receive the secret material; a signing service resolves references out of
band. Reference fields are documented as such and must never be logged.

Relationships reuse existing DevForge infrastructure (spec §44): Organization,
Project, User, and the Deployment/Build/Audit systems — no duplicate tenanting.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


# --- enumerations --------------------------------------------------------------
class ConnectionStatus(models.TextChoices):
    NOT_CONNECTED = "not_connected", "Not connected"
    INCOMPLETE = "incomplete", "Connection incomplete"      # missing permission/verify failed
    CONNECTED = "connected", "Connected"                    # only when a live verify succeeds


class MobilePlatform(models.TextChoices):
    ANDROID = "android", "Android"
    IOS = "ios", "iOS"
    HARMONY = "harmony", "HarmonyOS / Huawei"


class SigningMode(models.TextChoices):
    DEVFORGE_MANAGED = "managed", "DevForge-managed"
    CUSTOMER_MANAGED = "customer", "Customer-managed"


class ReleaseState(models.TextChoices):
    # spec §21 — common states across every provider
    DRAFT = "draft", "Draft"
    BUILDING = "building", "Building"
    BUILD_READY = "build_ready", "Build ready"
    SIGNING = "signing", "Signing"
    SIGNED = "signed", "Signed"
    METADATA_INCOMPLETE = "metadata_incomplete", "Metadata incomplete"
    READY_FOR_TESTING = "ready_for_testing", "Ready for testing"
    TESTING = "testing", "Testing"
    READY_FOR_SUBMISSION = "ready_for_submission", "Ready for submission"
    SUBMITTED = "submitted", "Submitted"
    IN_REVIEW = "in_review", "In review"
    REJECTED = "rejected", "Rejected"
    APPROVED = "approved", "Approved"
    RELEASING = "releasing", "Releasing"
    RELEASED = "released", "Released"
    FAILED = "failed", "Failed"
    BLOCKED = "blocked", "Blocked"


# --- credentials (references only — never secrets) -----------------------------
class StoreConnection(models.Model):
    """A tenant's authorized link to a store account (spec §5, §26).

    `credential_reference` is an OPAQUE handle into a vault — never the secret. A
    connection is CONNECTED only after a live verify succeeds; until then it stays
    NOT_CONNECTED/INCOMPLETE. DevForge never stores broader scopes than granted and
    never requests broader silently (spec §6)."""

    provider = models.CharField(max_length=32)  # providers.get_provider key
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="store_connections"
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="store_connections",
    )
    external_account_id = models.CharField(max_length=255, blank=True)
    credential_type = models.CharField(max_length=64, blank=True)   # e.g. "service_account"
    credential_reference = models.CharField(
        max_length=255, blank=True,
        help_text="Opaque vault handle — NEVER a secret. Redact from logs.",
    )
    scopes = models.JSONField(default=list, blank=True)             # granted permissions
    status = models.CharField(
        max_length=20, choices=ConnectionStatus.choices, default=ConnectionStatus.NOT_CONNECTED
    )
    detail = models.CharField(max_length=500, blank=True)          # why incomplete, etc.
    last_verified = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "provider"], name="uniq_org_store_provider"
            )
        ]

    def __str__(self):
        return f"{self.organization.name} · {self.provider} ({self.status})"


# --- application identity ------------------------------------------------------
class MobileApplication(models.Model):
    """Provider-independent app record (spec §14). Identity is protected once a
    release has shipped (spec §7): package/bundle changes are guarded in service."""

    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="mobile_applications"
    )
    name = models.CharField(max_length=255)
    package_identifier = models.CharField(max_length=255, blank=True)  # Android: com.x.y
    bundle_identifier = models.CharField(max_length=255, blank=True)   # iOS: com.x.y
    version = models.CharField(max_length=32, default="1.0.0")
    build_number = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.version}+{self.build_number})"


class StoreApplication(models.Model):
    """Per-store projection of a MobileApplication (spec §14, §40)."""

    mobile_application = models.ForeignKey(
        MobileApplication, on_delete=models.CASCADE, related_name="store_apps"
    )
    connection = models.ForeignKey(
        StoreConnection, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="store_apps",
    )
    provider = models.CharField(max_length=32)
    external_app_id = models.CharField(max_length=255, blank=True)
    metadata_status = models.CharField(max_length=32, default="incomplete")
    signing_status = models.CharField(max_length=32, default="not_configured")
    release_status = models.CharField(max_length=32, default="none")
    review_status = models.CharField(max_length=32, default="none")
    last_synced = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["provider"]
        constraints = [
            models.UniqueConstraint(
                fields=["mobile_application", "provider"], name="uniq_app_store_provider"
            )
        ]

    def __str__(self):
        return f"{self.mobile_application.name} @ {self.provider}"


# --- builds & signing ----------------------------------------------------------
class MobileBuild(models.Model):
    """A produced artifact for one platform (spec §36). Offline, DevForge records
    the intent to build; it does not fake a compiled binary it cannot produce."""

    mobile_application = models.ForeignKey(
        MobileApplication, on_delete=models.CASCADE, related_name="builds"
    )
    platform = models.CharField(max_length=16, choices=MobilePlatform.choices)
    version = models.CharField(max_length=32)
    build_number = models.PositiveIntegerField()
    artifact_format = models.CharField(max_length=16, blank=True)   # aab/ipa/apk
    artifact_path = models.CharField(max_length=1024, blank=True)   # empty until real build exists
    source_commit = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=32, default="planned")     # planned/ready/failed
    detail = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.mobile_application.name} {self.platform} {self.version}+{self.build_number}"


class SigningConfiguration(models.Model):
    """How an app is signed (spec §8, §11). Holds only a credential *reference*; the
    secret lives in a vault and is resolved by a signing service — never here, never
    to an agent (spec §27)."""

    mobile_application = models.ForeignKey(
        MobileApplication, on_delete=models.CASCADE, related_name="signing_configs"
    )
    platform = models.CharField(max_length=16, choices=MobilePlatform.choices)
    mode = models.CharField(max_length=16, choices=SigningMode.choices, default=SigningMode.DEVFORGE_MANAGED)
    credential_reference = models.CharField(
        max_length=255, blank=True,
        help_text="Opaque vault handle for signing material — NEVER a key/password.",
    )
    configured = models.BooleanField(default=False)
    detail = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["platform"]

    def __str__(self):
        return f"{self.mobile_application.name} {self.platform} signing ({self.mode})"


# --- metadata ------------------------------------------------------------------
class StoreMetadata(models.Model):
    """Common metadata, projected per store by an adapter (spec §15, §16)."""

    store_application = models.OneToOneField(
        StoreApplication, on_delete=models.CASCADE, related_name="metadata"
    )
    app_name = models.CharField(max_length=255, blank=True)
    short_description = models.CharField(max_length=255, blank=True)
    full_description = models.TextField(blank=True)
    keywords = models.CharField(max_length=500, blank=True)
    category = models.CharField(max_length=128, blank=True)
    support_url = models.URLField(blank=True)
    privacy_url = models.URLField(blank=True)
    ai_generated = models.BooleanField(default=False)   # spec §16 — mark AI drafts
    approved = models.BooleanField(default=False)       # never auto-submit declarations
    # Structured draft extras + provenance: feature_descriptions, screenshot_captions,
    # the features it was built from, and the source (model name or "detected-features").
    generated = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"metadata for {self.store_application}"


class StoreAsset(models.Model):
    """A visual asset for a store listing — screenshot / icon / feature graphic
    (spec §17, §36).

    `source` records how it was produced, honestly:
      - "schematic" : a device-framed LAYOUT generated from the app's real screen
                      definitions (screen name + its actual components). It represents
                      the app's structure; it is NOT a pixel capture of the running app.
      - "live"      : a real capture of the running application (needs the app running
                      under a headless browser / simulator — gated on that infra).
    Assets are drafts until a human approves; nothing is auto-submitted.
    """

    KIND_SCREENSHOT = "screenshot"
    KIND_ICON = "icon"
    KIND_FEATURE = "feature_graphic"

    store_application = models.ForeignKey(
        StoreApplication, on_delete=models.CASCADE, related_name="assets"
    )
    kind = models.CharField(max_length=24, default=KIND_SCREENSHOT)
    screen_name = models.CharField(max_length=255, blank=True)
    slot = models.CharField(max_length=64, blank=True)     # device slot, e.g. "phone_6.7"
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    source = models.CharField(max_length=16, default="schematic")
    fmt = models.CharField(max_length=8, default="svg")
    svg = models.TextField(blank=True)                     # inline vector for schematic previews
    path = models.CharField(max_length=1024, blank=True)   # set only for real captured files
    caption = models.CharField(max_length=255, blank=True)
    approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["slot", "id"]

    def __str__(self):
        return f"{self.kind} {self.screen_name} ({self.width}x{self.height}, {self.source})"


# --- releases ------------------------------------------------------------------
class Release(models.Model):
    """A traceable release of one app to one store (spec §22)."""

    mobile_application = models.ForeignKey(
        MobileApplication, on_delete=models.CASCADE, related_name="releases"
    )
    store_application = models.ForeignKey(
        StoreApplication, on_delete=models.CASCADE, related_name="releases"
    )
    provider = models.CharField(max_length=32)
    version = models.CharField(max_length=32)
    build_number = models.PositiveIntegerField()
    build = models.ForeignKey(
        MobileBuild, on_delete=models.SET_NULL, null=True, blank=True, related_name="releases"
    )
    environment = models.CharField(max_length=32, default="production")
    state = models.CharField(max_length=32, choices=ReleaseState.choices, default=ReleaseState.DRAFT)
    readiness = models.PositiveSmallIntegerField(default=0)   # 0-100, honest checks only
    source_commit = models.CharField(max_length=64, blank=True)
    external_reference = models.CharField(max_length=255, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="created_releases",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.mobile_application.name} {self.version}+{self.build_number} → {self.provider} ({self.state})"


class ReleaseCheck(models.Model):
    """One readiness check result (spec §18). Passing all checks means "ready to
    submit" — NEVER "guaranteed approval"."""

    release = models.ForeignKey(Release, on_delete=models.CASCADE, related_name="checks")
    key = models.CharField(max_length=64)
    label = models.CharField(max_length=255)
    status = models.CharField(max_length=16)   # ok / warn / fail / manual
    detail = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.key}={self.status}"


class ReleaseApproval(models.Model):
    """Human approval gate for sensitive operations (spec §28)."""

    release = models.ForeignKey(Release, on_delete=models.CASCADE, related_name="approvals")
    action = models.CharField(max_length=64)   # submit / change_signing / change_identity
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="release_approvals",
    )
    approved_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.action} approved for {self.release_id}"


class ReleaseEvent(models.Model):
    """Timeline of everything that happened to a release (spec §22, §31)."""

    release = models.ForeignKey(Release, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=64)
    message = models.CharField(max_length=500)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="release_events",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.kind}: {self.message}"


class ReleaseRejection(models.Model):
    """A store rejection and DevForge's analysis of it (spec §23).

    `raw_text` is the store's actual message — from the store API when connected, or
    pasted by the customer from the rejection they received. `source` records which."""

    release = models.ForeignKey(Release, on_delete=models.CASCADE, related_name="rejections")
    provider = models.CharField(max_length=32)
    source = models.CharField(max_length=16, default="manual")   # manual / store_api
    raw_text = models.TextField()
    category = models.CharField(max_length=32, blank=True)
    label = models.CharField(max_length=128, blank=True)
    summary = models.CharField(max_length=500, blank=True)
    recommendation = models.CharField(max_length=1000, blank=True)
    compliance_sensitive = models.BooleanField(default=False)
    affected_capabilities = models.JSONField(default=list, blank=True)
    # The DevForge change created to fix it (its normal approval-gated modify loop).
    change = models.ForeignKey(
        "changes.ChangeRequest", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="rejections",
    )
    resolved = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reported_rejections",
    )
    created_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.provider} rejection of {self.release_id} ({self.category})"


# --- configurable store requirements (spec §20) --------------------------------
class StoreRequirement(models.Model):
    """A store rule that gates a release (e.g. Google Play's testing period). Made
    configurable/versioned so it can change when the store changes — never
    hardcoded forever (spec §20)."""

    provider = models.CharField(max_length=32)
    key = models.CharField(max_length=64)
    label = models.CharField(max_length=255)
    value = models.JSONField(default=dict, blank=True)   # e.g. {"testers": 12, "days": 14}
    active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["provider", "key"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "key", "version"], name="uniq_store_requirement_version"
            )
        ]

    def __str__(self):
        return f"{self.provider}:{self.key} v{self.version}"
