"""Tests for the Mobile Release & App Store Platform.

The through-line is HONESTY (spec §43): no store is connected on this host, so the
platform must prepare everything it can offline and then tell the truth — never a
fake "Connected" or a fake submission.
"""
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.organizations.models import Membership, Organization, Role
from apps.projects.models import Project
from apps.release import service as rel
from apps.release.capabilities import StoreCapability
from apps.release.models import ConnectionStatus, ReleaseState
from apps.release.providers import StoreError, all_providers, get_provider


class ProviderTests(TestCase):
    def test_three_providers_registered(self):
        keys = {p.key for p in all_providers()}
        self.assertEqual(keys, {"google_play", "apple_app_store", "huawei_appgallery"})

    def test_capability_maps_differ(self):
        # Apple exposes app creation via API; Google Play does not (manual first step).
        apple = get_provider("apple_app_store")
        google = get_provider("google_play")
        self.assertTrue(apple.supports(StoreCapability.APPLICATION_CREATION))
        self.assertFalse(google.supports(StoreCapability.APPLICATION_CREATION))
        # Huawei has no beta-testing API surface assumed.
        huawei = get_provider("huawei_appgallery")
        self.assertFalse(huawei.supports(StoreCapability.BETA_TESTING))

    def test_none_available_offline(self):
        self.assertTrue(all(not p.is_available() for p in all_providers()))

    def test_operations_raise_honest_error(self):
        google = get_provider("google_play")
        with self.assertRaises(StoreError) as ctx:
            google.submit_for_review(release=None)
        self.assertIn("not connected", str(ctx.exception).lower())


class ConnectionTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="o@acme.com", password="x")
        self.org = Organization.objects.create(name="Acme", created_by=self.owner)

    def test_connect_is_honest_not_fake(self):
        conn = rel.connect_store(
            organization=self.org, provider_key="google_play", owner=self.owner,
            credential_reference="vault://ref-123", credential_type="service_account",
        )
        # Offline verify fails → connection is INCOMPLETE, never CONNECTED.
        self.assertEqual(conn.status, ConnectionStatus.INCOMPLETE)
        self.assertIn("not connected", conn.detail.lower())

    def test_no_secret_stored(self):
        conn = rel.connect_store(
            organization=self.org, provider_key="google_play",
            credential_reference="vault://ref-123",
        )
        # Only an opaque reference is stored — a vault handle, not a key.
        self.assertEqual(conn.credential_reference, "vault://ref-123")
        self.assertNotIn("BEGIN", conn.credential_reference)


class ReleaseFlowTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="o@acme.com", password="x")
        self.org = Organization.objects.create(name="Acme", created_by=self.owner)
        self.project = Project.objects.create(organization=self.org, name="Field CRM", created_by=self.owner)
        self.app = rel.create_mobile_application(
            project=self.project, name="Field CRM", package_identifier="com.acme.fieldcrm",
        )

    def test_readiness_starts_low_and_is_not_guaranteed(self):
        release = rel.request_release(app=self.app, provider_key="google_play", user=self.owner)
        # Nothing configured yet → not ready.
        self.assertLess(release.readiness, 60)
        # Metadata + privacy are missing → the precise, honest state, not "ready".
        self.assertEqual(release.state, ReleaseState.METADATA_INCOMPLETE)
        keys = {c.key: c.status for c in release.checks.all()}
        self.assertEqual(keys["build"], "fail")
        self.assertEqual(keys["signing"], "fail")
        self.assertEqual(keys["connection"], "manual")  # honest — store not connected

    def test_readiness_improves_when_configured(self):
        import tempfile
        rel.register_build(self.app, platform="android", artifact_format="aab",
                           artifact_path=tempfile.mktemp(), status="ready")
        rel.configure_signing(self.app, platform="android", mode="managed", configured=True)
        store_app = rel.ensure_store_application(self.app, "google_play")
        rel.set_metadata(store_app, app_name="Field CRM", short_description="CRM",
                         full_description="A CRM for field teams.", privacy_url="https://acme.com/privacy",
                         approved=True)
        release = rel.request_release(app=self.app, provider_key="google_play", user=self.owner)
        self.assertGreaterEqual(release.readiness, 80)
        # Even fully configured, the store connection is a manual step → not 100%.
        self.assertLess(release.readiness, 100)

    def test_submit_requires_approval(self):
        release = rel.request_release(app=self.app, provider_key="google_play", user=self.owner)
        with self.assertRaises(rel.ReleaseServiceError):
            rel.submit_release(release, user=self.owner)

    def test_submit_is_blocked_honestly_not_faked(self):
        release = rel.request_release(app=self.app, provider_key="google_play", user=self.owner)
        rel.approve_release(release, user=self.owner)
        release = rel.submit_release(release, user=self.owner)
        # Store is not connected → BLOCKED with a manual-action event, NOT "submitted".
        self.assertEqual(release.state, ReleaseState.BLOCKED)
        self.assertIsNone(release.submitted_at)
        self.assertTrue(release.events.filter(kind="manual_action_required").exists())

    def test_identity_locked_after_release(self):
        release = rel.request_release(app=self.app, provider_key="google_play", user=self.owner)
        release.state = ReleaseState.RELEASED
        release.save(update_fields=["state"])
        with self.assertRaises(rel.ReleaseServiceError):
            rel.set_identity(self.app, package_identifier="com.acme.somethingelse")


class CapabilityTests(TestCase):
    def test_mobile_publishing_is_planned_not_available(self):
        from apps.capabilities.registry import get
        cap = get("mobile_publishing")
        self.assertIsNotNone(cap)
        self.assertFalse(cap.is_available)  # honest — live publishing not wired yet


class ReleaseCenterUITests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="o@acme.com", password="x")
        self.org = Organization.objects.create(name="Acme", created_by=self.owner)
        Membership.objects.create(organization=self.org, user=self.owner, role=Role.OWNER)
        self.project = Project.objects.create(organization=self.org, name="Field CRM", created_by=self.owner)
        self.client.force_login(self.owner)

    def test_page_offers_setup_and_stays_honest(self):
        r = self.client.get(reverse("dashboard:release_center", args=[self.project.id]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Release Center")
        self.assertContains(r, "Set up mobile release")

    def test_create_app_then_shows_stores_not_connected(self):
        self.client.post(reverse("dashboard:release_center", args=[self.project.id]),
                         {"action": "create_app"})
        r = self.client.get(reverse("dashboard:release_center", args=[self.project.id]))
        self.assertContains(r, "Google Play")
        self.assertContains(r, "Apple App Store")
        self.assertContains(r, "Huawei AppGallery")
        self.assertContains(r, "Not connected")   # never a fake green light

    def test_admin_mobile_page(self):
        staff = User.objects.create_user(email="s@devforge.local", password="x", is_staff=True)
        self.client.force_login(staff)
        r = self.client.get(reverse("console:mobile"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Store providers")
        self.assertContains(r, "Google Play")
