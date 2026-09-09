"""Tests for the Website Creation & Publishing platform (Phase 1).

Through-line: DevForge really builds, snapshots, serves, health-checks and rolls
back a site — and never shows "Live"/served when it isn't (spec §50).
"""
import tempfile

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.organizations.models import Membership, Organization, Role
from apps.projects.models import Project
from apps.publishing import readiness as rd
from apps.publishing import service as pub
from apps.publishing.hosting import DevForgeLocalHost, HostError, get_host
from apps.repositories.service import repo_for_project

PAGE = "<html><head><title>Acme</title><meta name='description' content='Acme site'></head><body>Hi</body></html>"


class HostTests(TestCase):
    def test_local_host_available_cloud_hosts_not(self):
        self.assertTrue(DevForgeLocalHost().is_available())
        for key in ("vercel", "cloudflare", "aws", "digitalocean"):
            self.assertFalse(get_host(key).is_available())

    def test_cloud_host_refuses_honestly(self):
        with self.assertRaises(HostError) as ctx:
            get_host("vercel").publish(version=None)
        self.assertIn("not configured", str(ctx.exception).lower())


class ReadinessTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(organization=self.org, name="Acme Site")

    def test_no_build_blocks_publish(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = pub.get_or_create_website(self.project)
            checks = rd.evaluate(site)
            build = {c.key: c.status for c in checks}["build"]
            self.assertEqual(build, "fail")
            self.assertFalse(rd.can_publish(checks))

    def test_built_site_with_seo_passes(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            repo = repo_for_project(self.project); repo.init()
            repo.write_files({"index.html": PAGE}); repo.commit("seed")
            site = pub.get_or_create_website(self.project)
            status = {c.key: c.status for c in rd.evaluate(site)}
            self.assertEqual(status["build"], "ok")
            self.assertEqual(status["seo"], "ok")


class PublishFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="o@acme.com", password="x")
        self.org = Organization.objects.create(name="Acme", created_by=self.user)
        self.project = Project.objects.create(organization=self.org, name="Acme Site", created_by=self.user)

    def _seed(self):
        repo = repo_for_project(self.project); repo.init()
        repo.write_files({"index.html": PAGE}); repo.commit("seed")

    def test_publish_serves_a_real_url(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            self._seed()
            site = pub.get_or_create_website(self.project)
            version = pub.publish(site, user=self.user)
            self.assertEqual(version.state, "live")
            self.assertEqual(version.health, "healthy")
            self.assertTrue(version.is_current)
            self.assertEqual(version.version, "v1.0.0")
            # The served URL actually returns the built page.
            r = self.client.get(version.url)
            self.assertEqual(r.status_code, 200)
            self.assertIn(b"Acme", b"".join(r.streaming_content))

    def test_no_build_fails_honestly_not_fake_live(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = pub.get_or_create_website(self.project)
            version = pub.publish(site, user=self.user)
            self.assertEqual(version.state, "failed")
            self.assertEqual(version.url, "")
            self.assertFalse(version.is_current)

    def test_second_publish_bumps_version_and_rollback(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            self._seed()
            site = pub.get_or_create_website(self.project)
            v1 = pub.publish(site, user=self.user)
            v2 = pub.publish(site, user=self.user)
            self.assertEqual(v2.version, "v1.0.1")
            self.assertTrue(v2.is_current)
            back = pub.rollback(site, user=self.user)
            self.assertEqual(back.pk, v1.pk)
            self.assertTrue(back.is_current)

    def test_serve_blocks_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            self._seed()
            site = pub.get_or_create_website(self.project)
            pub.publish(site, user=self.user)
            r = self.client.get(f"/sites/{site.subdomain}/../../../etc/passwd")
            self.assertIn(r.status_code, (404, 400))


class _FakeResolver:
    """A test resolver so the verification flow runs without network."""
    def __init__(self, records=None, available=True, raises=False):
        self._records = records or {}
        self._available = available
        self._raises = raises

    def available(self):
        return self._available

    def txt(self, name):
        if self._raises:
            raise RuntimeError("NXDOMAIN")
        return self._records.get(name, [])


class CustomDomainTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="o@acme.com", password="x")
        self.org = Organization.objects.create(name="Acme", created_by=self.user)
        self.project = Project.objects.create(organization=self.org, name="Acme Site", created_by=self.user)
        self.site = None

    def _website(self, tmp):
        return pub.get_or_create_website(self.project)

    def test_connect_generates_token_and_records(self):
        from apps.publishing import domain_service as dom
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._website(tmp)
            d = dom.connect_domain(site, hostname="www.acme.com", user=self.user)
            self.assertTrue(d.verification_token)
            types = {r["type"] for r in d.required_records}
            self.assertIn("TXT", types)
            self.assertIn("CNAME", types)  # subdomain → CNAME
            self.assertEqual(d.verification_status, "pending")
            self.assertEqual(d.ssl_status, "none")

    def test_apex_uses_alias_record(self):
        from apps.publishing import domain_service as dom
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            d = dom.connect_domain(self._website(tmp), hostname="acme.com", user=self.user)
            types = {r["type"] for r in d.required_records}
            self.assertTrue(any("ALIAS" in t for t in types))

    def test_rejects_invalid_hostname(self):
        from apps.publishing import domain_service as dom
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            with self.assertRaises(dom.DomainServiceError):
                dom.connect_domain(self._website(tmp), hostname="not a domain", user=self.user)

    def test_verify_only_when_token_present(self):
        from apps.publishing import domain_service as dom
        from apps.publishing.domains import verify_name
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            d = dom.connect_domain(self._website(tmp), hostname="www.acme.com", user=self.user)
            # Wrong/absent record → not verified.
            dom.verify_domain(d, resolver=_FakeResolver({verify_name("www.acme.com"): ["someone-else"]}))
            self.assertEqual(d.verification_status, "failed")
            self.assertFalse(d.is_verified)
            # Correct token present → verified, and SSL becomes pending (not active).
            dom.verify_domain(d, resolver=_FakeResolver({verify_name("www.acme.com"): [d.verification_token]}))
            self.assertTrue(d.is_verified)
            self.assertEqual(d.ssl_status, "pending")
            self.assertFalse(d.is_live)   # pending SSL → not live

    def test_verify_honest_when_resolver_unavailable(self):
        from apps.publishing import domain_service as dom
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            d = dom.connect_domain(self._website(tmp), hostname="www.acme.com", user=self.user)
            dom.verify_domain(d, resolver=_FakeResolver(available=False))
            self.assertEqual(d.verification_status, "pending")   # never faked
            self.assertIn("could not be checked", d.detail.lower())

    def test_ssl_requires_verification_and_never_active_offline(self):
        from apps.publishing import domain_service as dom
        from apps.publishing.domains import verify_name
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            d = dom.connect_domain(self._website(tmp), hostname="www.acme.com", user=self.user)
            with self.assertRaises(dom.DomainServiceError):
                dom.request_ssl(d)   # not verified yet
            dom.verify_domain(d, resolver=_FakeResolver({verify_name("www.acme.com"): [d.verification_token]}))
            dom.request_ssl(d, user=self.user)
            self.assertEqual(d.ssl_status, "pending")   # honest — no real cert here
            self.assertNotEqual(d.ssl_status, "active")

    def test_dns_providers_gated(self):
        from apps.publishing.domains import get_dns_provider
        self.assertTrue(get_dns_provider("manual").is_available())
        self.assertFalse(get_dns_provider("cloudflare").is_available())


POOR_PAGE = "<html><body><h1>Welcome</h1><p>We build bridges for cities across the region.</p><img src='a.png'></body></html>"


class SeoEngineTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="o@acme.com", password="x")
        self.org = Organization.objects.create(name="Acme", created_by=self.user)
        self.project = Project.objects.create(organization=self.org, name="Acme Engineering", created_by=self.user)

    def _seed(self, files):
        repo = repo_for_project(self.project); repo.init()
        repo.write_files(files); repo.commit("seed")
        return pub.get_or_create_website(self.project)

    def test_audit_flags_real_gaps(self):
        from apps.publishing import seo
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._seed({"index.html": POOR_PAGE})
            audit = seo.audit_pages(site)[0]
            status = {f["key"]: f["status"] for f in audit.findings}
            self.assertEqual(status["title"], "fail")        # no <title>
            self.assertEqual(status["description"], "fail")  # no meta description
            self.assertEqual(status["h1"], "ok")             # has <h1>
            self.assertEqual(status["alt"], "warn")          # img without alt

    def test_generate_drafts_from_real_content(self):
        from apps.publishing import seo_service as seo_svc
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._seed({"index.html": POOR_PAGE})
            drafts = seo_svc.generate_drafts(site, user=self.user)
            self.assertEqual(len(drafts), 1)
            page = drafts[0]
            self.assertTrue(page.ai_generated)
            self.assertFalse(page.approved)
            self.assertLessEqual(len(page.title), 200)
            # Drawn from the real heading/content, not invented.
            self.assertIn("Welcome", page.title)
            self.assertIn("bridges", page.description.lower())

    def test_sitemap_and_robots_are_real(self):
        from apps.publishing import seo
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._seed({"index.html": POOR_PAGE, "about.html": POOR_PAGE})
            sitemap = seo.build_sitemap(site)
            self.assertIn("<urlset", sitemap)
            self.assertEqual(sitemap.count("<loc>"), 2)
            self.assertIn("Sitemap:", seo.build_robots(site, allow=True))
            self.assertIn("Disallow: /", seo.build_robots(site, allow=False))

    def test_apply_writes_files_and_injects_meta(self):
        from apps.publishing import seo_service as seo_svc
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._seed({"index.html": POOR_PAGE})
            seo_svc.generate_drafts(site, user=self.user)
            config = seo_svc.ensure_config(site)
            config.pages.update(approved=True)
            result = seo_svc.apply_seo(site, user=self.user)
            self.assertEqual(result["pages"], 1)
            repo = repo_for_project(self.project)
            self.assertIn("sitemap.xml", repo.list_files())
            self.assertIn("robots.txt", repo.list_files())
            html = (repo.path / "index.html").read_text()
            self.assertIn("<title>", html)                 # meta injected
            self.assertIn('name="description"', html)
            self.assertIn("devforge:seo", html)

    def test_apply_is_idempotent(self):
        from apps.publishing import seo
        applied = seo.apply_meta_to_html(
            "<html><head></head><body>x</body></html>",
            {"title": "A", "description": "B"})
        twice = seo.apply_meta_to_html(applied, {"title": "A", "description": "B"})
        self.assertEqual(twice.count("devforge:seo -->"), 2)  # one open + one close marker only


class FormsAndLeadsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="owner@acme.com", password="x")
        self.org = Organization.objects.create(name="Acme", created_by=self.user)
        self.project = Project.objects.create(organization=self.org, name="Acme Site", created_by=self.user)

    def _site(self, tmp):
        return pub.get_or_create_website(self.project)

    def test_create_form_has_default_fields(self):
        from apps.publishing import forms_service as forms
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            form = forms.create_form(self._site(tmp), kind="quote", user=self.user)
            names = {f["name"] for f in form.fields}
            self.assertEqual(names, {"name", "email", "phone", "message"})
            self.assertEqual(form.notify_email, "owner@acme.com")   # defaults to owner

    def test_submission_creates_lead_and_sends_email(self):
        from django.core import mail
        from apps.publishing import forms_service as forms
        from apps.publishing.models import Lead
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            form = forms.create_form(self._site(tmp), kind="contact", user=self.user)
            sub, lead = forms.submit(form, {"name": "Jo", "email": "jo@x.com", "message": "Hi there"})
            self.assertIsInstance(lead, Lead)
            self.assertEqual(lead.name, "Jo")
            self.assertEqual(lead.email, "jo@x.com")
            self.assertEqual(Lead.objects.count(), 1)
            self.assertEqual(len(mail.outbox), 1)              # notification really sent
            self.assertTrue(sub.email_notified)

    def test_validation_rejects_missing_required(self):
        from apps.publishing import forms_service as forms
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            form = forms.create_form(self._site(tmp), kind="contact", user=self.user)
            with self.assertRaises(forms.FormError):
                forms.submit(form, {"name": "Jo"})            # no email/message
            with self.assertRaises(forms.FormError):
                forms.submit(form, {"name": "Jo", "email": "bad", "message": "x"})  # bad email

    def test_honeypot_drops_spam_no_lead(self):
        from apps.publishing import forms_service as forms
        from apps.publishing.models import Lead
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            form = forms.create_form(self._site(tmp), kind="contact", user=self.user)
            sub, lead = forms.submit(form, {"name": "Bot", "email": "b@x.com",
                                            "message": "spam", "_gotcha": "iamabot"})
            self.assertIsNone(lead)
            self.assertTrue(sub.is_spam)
            self.assertEqual(Lead.objects.count(), 0)

    def test_no_email_configured_still_captures_lead(self):
        from apps.publishing import forms_service as forms
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            form = forms.create_form(self._site(tmp), kind="contact", user=self.user)
            form.notify_email = ""; form.save()
            sub, lead = forms.submit(form, {"name": "Jo", "email": "jo@x.com", "message": "Hi"})
            self.assertIsNotNone(lead)               # lead captured
            self.assertFalse(sub.email_notified)     # honest: no email sent

    def test_public_endpoint_creates_lead(self):
        from apps.publishing import forms_service as forms
        from apps.publishing.models import Lead
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site(tmp)
            form = forms.create_form(site, kind="contact", user=self.user)
            r = self.client.post(
                reverse("publishing:submit_form", args=[site.subdomain, form.slug]),
                {"name": "Web Visitor", "email": "v@x.com", "message": "From the site"},
            )
            self.assertEqual(r.status_code, 302)     # redirect back to the site
            self.assertEqual(Lead.objects.filter(name="Web Visitor").count(), 1)

    def test_embed_snippet_points_at_endpoint(self):
        from apps.publishing import forms_service as forms
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site(tmp)
            form = forms.create_form(site, kind="contact", user=self.user)
            html = forms.embed_html(form, action_base="https://devforge.app")
            self.assertIn(f"/sites/{site.subdomain}/f/{form.slug}", html)
            self.assertIn('name="_gotcha"', html)    # honeypot present

    def test_leads_inbox_page(self):
        from apps.publishing import forms_service as forms
        Membership.objects.create(organization=self.org, user=self.user, role=Role.OWNER)
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site(tmp)
            form = forms.create_form(site, kind="contact", user=self.user)
            forms.submit(form, {"name": "Jo", "email": "jo@x.com", "message": "Hi"})
            self.client.force_login(self.user)
            r = self.client.get(reverse("dashboard:leads", args=[self.project.id]))
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, "jo@x.com")


def _png_bytes(w=100, h=60, color=(200, 40, 40)):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


class AssetManagementTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="owner@acme.com", password="x")
        self.org = Organization.objects.create(name="Acme", created_by=self.user)
        self.project = Project.objects.create(organization=self.org, name="Acme Site", created_by=self.user)

    def _site(self):
        return pub.get_or_create_website(self.project)

    def test_upload_stores_real_image_with_dims(self):
        from apps.publishing import assets_service as a
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            asset = a.store_asset(self._site(), filename="Logo File.png", data=_png_bytes(120, 80),
                                  content_type="image/png", user=self.user)
            self.assertEqual(asset.kind, "image")
            self.assertEqual((asset.width, asset.height), (120, 80))
            self.assertEqual(asset.path, "assets/Logo-File.png")   # sanitized
            # It's really in the repo (so it publishes with the site).
            self.assertIn("assets/Logo-File.png", repo_for_project(self.project).list_files())

    def test_rejects_bad_extension_and_oversize(self):
        from apps.publishing import assets_service as a
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            with self.assertRaises(a.AssetError):
                a.store_asset(site, filename="evil.php", data=b"<?php ?>", user=self.user)
            with self.assertRaises(a.AssetError):
                a.store_asset(site, filename="huge.png", data=b"x" * (a.MAX_SIZE + 1), user=self.user)

    def test_rejects_fake_image(self):
        from apps.publishing import assets_service as a
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            with self.assertRaises(a.AssetError):   # .png that isn't an image
                a.store_asset(self._site(), filename="notreally.png", data=b"not an image",
                              user=self.user)

    def test_resize_is_real(self):
        from apps.publishing import assets_service as a
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            asset = a.store_asset(self._site(), filename="pic.png", data=_png_bytes(200, 100),
                                  user=self.user)
            a.resize_image(asset, width=100, user=self.user)
            self.assertEqual((asset.width, asset.height), (100, 50))   # aspect preserved
            from PIL import Image
            import io
            with Image.open(io.BytesIO(a.read_bytes(asset))) as im:
                self.assertEqual(im.size, (100, 50))                   # the file really changed

    def test_compress_reduces_or_keeps_and_delete(self):
        from apps.publishing import assets_service as a
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            asset = a.store_asset(site, filename="pic.jpg", data=_jpeg_bytes(), user=self.user)
            before = asset.size
            a.compress_image(asset, quality=40, user=self.user)
            self.assertLessEqual(asset.size, before)
            a.delete_asset(asset, user=self.user)
            self.assertFalse(site.assets.filter(pk=asset.pk).exists())

    def test_non_image_cannot_be_resized(self):
        from apps.publishing import assets_service as a
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            asset = a.store_asset(self._site(), filename="doc.pdf", data=b"%PDF-1.4 fake",
                                  kind="document", user=self.user)
            with self.assertRaises(a.AssetError):
                a.resize_image(asset, width=100)

    def test_asset_raw_view_scoped_and_serves(self):
        from apps.publishing import assets_service as a
        Membership.objects.create(organization=self.org, user=self.user, role=Role.OWNER)
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            asset = a.store_asset(self._site(), filename="pic.png", data=_png_bytes(), user=self.user)
            self.client.force_login(self.user)
            r = self.client.get(reverse("dashboard:asset_raw", args=[self.project.id, asset.id]))
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r["Content-Type"], "image/png")
            # A user from another org cannot fetch it.
            other = User.objects.create_user(email="x@y.com", password="x")
            self.client.force_login(other)
            r2 = self.client.get(reverse("dashboard:asset_raw", args=[self.project.id, asset.id]))
            self.assertEqual(r2.status_code, 404)


def _jpeg_bytes(w=200, h=200):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (120, 120, 120)).save(buf, format="JPEG", quality=95)
    return buf.getvalue()


class AnalyticsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="owner@acme.com", password="x")
        self.org = Organization.objects.create(name="Acme", created_by=self.user)
        self.project = Project.objects.create(organization=self.org, name="Acme Site", created_by=self.user)

    def _published(self):
        repo = repo_for_project(self.project); repo.init()
        repo.write_files({"index.html": PAGE}); repo.commit("seed")
        site = pub.get_or_create_website(self.project)
        pub.publish(site, user=self.user)
        return site

    def test_record_stores_no_pii_and_hashes_session(self):
        from apps.publishing import analytics
        from django.test import RequestFactory
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = pub.get_or_create_website(self.project)
            req = RequestFactory().get("/sites/x/", HTTP_USER_AGENT="Mozilla/5.0 iPhone",
                                       REMOTE_ADDR="203.0.113.9")
            view = analytics.record_view(site, req)
            self.assertIsNotNone(view)
            self.assertEqual(view.device, "mobile")
            self.assertEqual(len(view.session_key), 32)
            self.assertNotIn("203.0.113.9", view.session_key)   # IP never stored
            # No model field holds the raw IP.
            self.assertFalse(any("203.0.113.9" in str(v) for v in view.__dict__.values()))

    def test_do_not_track_records_nothing(self):
        from apps.publishing import analytics
        from django.test import RequestFactory
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = pub.get_or_create_website(self.project)
            req = RequestFactory().get("/", HTTP_DNT="1", REMOTE_ADDR="203.0.113.9")
            self.assertIsNone(analytics.record_view(site, req))
            self.assertEqual(site.page_views.count(), 0)

    def test_serving_a_page_records_a_view(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._published()
            self.assertEqual(site.page_views.count(), 0)
            self.client.get(f"/sites/{site.subdomain}/", HTTP_USER_AGENT="Mozilla/5.0")
            self.assertEqual(site.page_views.filter(device="desktop").count(), 1)

    def test_summary_aggregates_and_excludes_bots(self):
        from apps.publishing import analytics
        from django.test import RequestFactory
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = pub.get_or_create_website(self.project)
            rf = RequestFactory()
            analytics.record_view(site, rf.get("/a", HTTP_USER_AGENT="Mozilla/5.0", REMOTE_ADDR="1.1.1.1"))
            analytics.record_view(site, rf.get("/a", HTTP_USER_AGENT="Mozilla/5.0", REMOTE_ADDR="2.2.2.2"))
            analytics.record_view(site, rf.get("/", HTTP_USER_AGENT="Googlebot/2.1", REMOTE_ADDR="3.3.3.3"))
            data = analytics.summary(site, days=30)
            self.assertEqual(data["pageviews"], 2)          # bot excluded
            self.assertEqual(data["sessions"], 2)           # two distinct sessions
            self.assertEqual(data["bot_views"], 1)
            self.assertEqual(data["top_pages"][0]["path"], "/a")

    def test_conversion_from_leads(self):
        from apps.publishing import analytics, forms_service as forms
        from django.test import RequestFactory
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = pub.get_or_create_website(self.project)
            analytics.record_view(site, RequestFactory().get("/", HTTP_USER_AGENT="Mozilla/5.0", REMOTE_ADDR="1.1.1.1"))
            form = forms.create_form(site, kind="contact", user=self.user)
            forms.submit(form, {"name": "Jo", "email": "jo@x.com", "message": "Hi"})
            data = analytics.summary(site, days=30)
            self.assertEqual(data["leads"], 1)
            self.assertEqual(data["conversion"], 100.0)     # 1 lead / 1 session

    def test_analytics_page_renders(self):
        Membership.objects.create(organization=self.org, user=self.user, role=Role.OWNER)
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            self._published()
            self.client.force_login(self.user)
            r = self.client.get(reverse("dashboard:analytics", args=[self.project.id]))
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, "Website analytics")
            self.assertContains(r, "Do-Not-Track")


BAD_A11Y = (
    "<html><head><title>x</title></head><body>"
    "<div>menu</div><h1>Hi</h1><h3>Skipped</h3>"
    "<img src='a.png'>"
    "<input type='text' name='email'>"
    "<a href='/x'><img src='i.png'></a>"
    "<button></button>"
    "<span tabindex='3'>x</span>"
    "<p style='color:#777;background:#888'>low</p>"
    "<style>a:focus{outline:none}</style>"
    "</body></html>"
)
GOOD_A11Y = (
    "<html lang='en'><head><title>x</title></head><body>"
    "<nav>menu</nav><main><h1>Hi</h1><h2>Sub</h2>"
    "<img src='a.png' alt='A logo'>"
    "<label for='e'>Email</label><input type='text' id='e' name='email'>"
    "<button>Send</button></main></body></html>"
)


class AccessibilityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="owner@acme.com", password="x")
        self.org = Organization.objects.create(name="Acme", created_by=self.user)
        self.project = Project.objects.create(organization=self.org, name="Acme Site", created_by=self.user)

    def _site(self, files):
        repo = repo_for_project(self.project); repo.init()
        repo.write_files(files); repo.commit("seed")
        return pub.get_or_create_website(self.project)

    def _status(self, html):
        from apps.publishing import accessibility as a11y
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site({"index.html": html})
            audit = a11y.audit_pages(site)[0]
            return {f["key"]: f["status"] for f in audit.findings}

    def test_flags_real_problems(self):
        s = self._status(BAD_A11Y)
        self.assertEqual(s["lang"], "fail")        # no <html lang>
        self.assertEqual(s["alt"], "fail")         # img without alt
        self.assertEqual(s["labels"], "fail")      # input with no label
        self.assertEqual(s["headings"], "warn")    # h1 → h3 skip
        self.assertEqual(s["landmarks"], "warn")   # no main/nav
        self.assertEqual(s["tabindex"], "warn")    # positive tabindex
        self.assertEqual(s["focus"], "warn")       # outline:none
        self.assertEqual(s["contrast"], "warn")    # #777 on #888 is low

    def test_clean_page_passes_detectable_checks(self):
        s = self._status(GOOD_A11Y)
        for key in ("lang", "alt", "labels", "headings", "landmarks"):
            self.assertEqual(s[key], "ok", key)

    def test_contrast_is_manual_without_inline_colors(self):
        s = self._status("<html lang='en'><body><main><nav>x</nav><h1>Hi</h1></main></body></html>")
        self.assertEqual(s["contrast"], "manual")  # honest — can't verify statically

    def test_empty_icon_link_flagged(self):
        s = self._status("<html lang='en'><body><a href='/'><svg></svg></a></body></html>")
        self.assertEqual(s["controls"], "warn")

    def test_page_renders_with_no_compliance_claim(self):
        Membership.objects.create(organization=self.org, user=self.user, role=Role.OWNER)
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            self._site({"index.html": GOOD_A11Y})
            self.client.force_login(self.user)
            r = self.client.get(reverse("dashboard:accessibility", args=[self.project.id]))
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, "does not guarantee full accessibility compliance")


class MonitoringTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="owner@acme.com", password="x")
        self.org = Organization.objects.create(name="Acme", created_by=self.user)
        self.project = Project.objects.create(organization=self.org, name="Acme Site", created_by=self.user)

    def _published(self):
        repo = repo_for_project(self.project); repo.init()
        repo.write_files({"index.html": PAGE}); repo.commit("seed")
        site = pub.get_or_create_website(self.project)
        pub.publish(site, user=self.user)
        return site

    def test_publish_records_a_health_check(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._published()
            self.assertEqual(site.health_checks.filter(status="up").count(), 1)

    def test_run_check_probes_real_serve_health(self):
        from apps.publishing import monitor
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._published()
            check = monitor.run_check(site)
            self.assertEqual(check.status, "up")            # snapshot present + readable
            self.assertGreaterEqual(check.response_ms, 0)

    def test_down_when_artifact_missing(self):
        import shutil
        from apps.publishing import monitor
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._published()
            shutil.rmtree(site.current.artifact_dir)        # simulate the served files vanishing
            check = monitor.run_check(site)
            self.assertEqual(check.status, "down")

    def test_uptime_summary_and_incidents(self):
        from apps.publishing import monitor
        from apps.publishing.models import HealthCheck
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._published()             # 1 up check from publish
            HealthCheck.objects.create(website=site, status="down")
            HealthCheck.objects.create(website=site, status="up")
            s = monitor.uptime_summary(site, days=7)
            self.assertEqual(s["checks"], 3)
            self.assertEqual(s["uptime_pct"], round(100 * 2 / 3, 2))
            self.assertEqual(s["incidents"], 1)   # one transition into down
            self.assertEqual(s["current"], "up")  # most recent

    def test_run_check_none_without_publish(self):
        from apps.publishing import monitor
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = pub.get_or_create_website(self.project)
            self.assertIsNone(monitor.run_check(site))   # nothing published to probe

    def test_monitoring_page_renders_with_honest_scope(self):
        Membership.objects.create(organization=self.org, user=self.user, role=Role.OWNER)
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            self._published()
            self.client.force_login(self.user)
            r = self.client.get(reverse("dashboard:monitoring", args=[self.project.id]))
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, "Uptime")
            self.assertContains(r, "Not monitored on DevForge hosting yet")


CLEAN_PAGE = (
    "<html lang='en'><head><title>Acme</title>"
    "<meta name='description' content='Acme builds things.'></head><body>"
    "<nav>menu</nav><main><h1>Acme</h1>"
    "<img src='a.png' alt='logo'>"
    "<label for='e'>Email</label><input id='e' name='email'>"
    "<button>Send</button></main></body></html>"
)


class OperationsAdvisorTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="owner@acme.com", password="x")
        self.org = Organization.objects.create(name="Acme", created_by=self.user)
        self.project = Project.objects.create(organization=self.org, name="Acme Site", created_by=self.user)

    def _publish(self, page=CLEAN_PAGE, extra=None):
        files = {"index.html": page}
        if extra:
            files.update(extra)
        repo = repo_for_project(self.project); repo.init()
        repo.write_files(files); repo.commit("seed")
        site = pub.get_or_create_website(self.project)
        pub.publish(site, user=self.user)
        return site

    def _keys(self, site):
        from apps.publishing import operations as ops
        return {f.key for f in ops.analyze(site)}

    def test_clean_site_is_healthy(self):
        from apps.publishing import operations as ops
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._publish()
            findings = ops.analyze(site)
            self.assertEqual(findings, [])
            self.assertIn("healthy", ops.summary_line(findings).lower())

    def test_flags_large_image(self):
        from apps.publishing.models import Asset
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._publish()
            Asset.objects.create(website=site, path="assets/huge.png", original_name="huge.png",
                                 kind="image", size=3 * 1024 * 1024, width=4000, height=3000)
            keys = self._keys(site)
            self.assertIn("large_images", keys)

    def test_flags_missing_seo(self):
        # A page with no title/description.
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._publish(page="<html lang='en'><body><main><nav>x</nav><h1>Hi</h1></main></body></html>")
            self.assertIn("seo_gaps", self._keys(site))

    def test_flags_accessibility(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._publish(page="<html><head><title>x</title><meta name='description' content='y'></head><body><img src='a.png'></body></html>")
            self.assertIn("a11y", self._keys(site))   # missing lang + alt

    def test_conversion_finding_when_traffic_and_no_form(self):
        from apps.publishing.models import PageView
        from django.utils import timezone
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._publish()
            today = timezone.now().date()
            for i in range(25):
                PageView.objects.create(website=site, path="/", device="desktop",
                                        session_key=f"sess{i:03d}", day=today)
            self.assertIn("no_capture", self._keys(site))

    def test_page_weight_creates_change_request(self):
        Membership.objects.create(organization=self.org, user=self.user, role=Role.OWNER)
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._publish(extra={"heavy.html": "<html lang='en'><body>" + "x" * 300000 + "</body></html>"})
            self.assertIn("page_weight", self._keys(site))
            self.client.force_login(self.user)
            r = self.client.post(reverse("dashboard:operations", args=[self.project.id]),
                                  {"action": "create_fix", "finding": "page_weight"})
            self.assertEqual(r.status_code, 302)
            self.assertIn("/changes/", r.headers["Location"])   # routed to approval-gated change
            self.assertEqual(self.project.changes.count(), 1)

    def test_operations_page_renders(self):
        Membership.objects.create(organization=self.org, user=self.user, role=Role.OWNER)
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            self._publish()
            self.client.force_login(self.user)
            r = self.client.get(reverse("dashboard:operations", args=[self.project.id]))
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, "nothing is applied automatically")


class CmsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="owner@acme.com", password="x")
        self.org = Organization.objects.create(name="Acme", created_by=self.user)
        self.project = Project.objects.create(organization=self.org, name="Acme Site", created_by=self.user)

    def _site(self):
        return pub.get_or_create_website(self.project)

    def test_blog_generates_index_and_detail_pages(self):
        from apps.publishing import cms_service as cms
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            blog = cms.create_collection(site, kind="blog", name="Blog", user=self.user)
            cms.add_item(blog, title="First Post", subtitle="hello", body="Line one.\n\nLine two.")
            result = cms.generate(site, user=self.user)
            paths = result["paths"]
            self.assertIn("blog/index.html", paths)
            self.assertIn("blog/first-post.html", paths)
            repo = repo_for_project(self.project)
            detail = (repo.path / "blog/first-post.html").read_text()
            self.assertIn("<h1>First Post</h1>", detail)
            self.assertIn("<p>Line one.</p>", detail)     # paragraphs rendered
            self.assertIn('lang="en"', detail)            # accessible output

    def test_faq_generates_single_page(self):
        from apps.publishing import cms_service as cms
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            faq = cms.create_collection(site, kind="faq", name="FAQs", user=self.user)
            cms.add_item(faq, title="How much?", body="It depends.")
            result = cms.generate(site, user=self.user)
            self.assertEqual(result["paths"], ["faqs.html"])
            html = (repo_for_project(self.project).path / "faqs.html").read_text()
            self.assertIn("How much?", html)

    def test_unpublished_items_excluded(self):
        from apps.publishing import cms_service as cms
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            blog = cms.create_collection(site, kind="blog", user=self.user)
            cms.add_item(blog, title="Draft", body="x", published=False)
            with self.assertRaises(cms.CmsError):   # only a draft → nothing to generate
                cms.generate(site, user=self.user)

    def test_generated_content_escapes_html(self):
        from apps.publishing import cms_service as cms
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            page = cms.create_collection(site, kind="page", name="Pages", user=self.user)
            cms.add_item(page, title="About", body="<script>alert(1)</script>")
            cms.generate(site, user=self.user)
            html = (repo_for_project(self.project).path / "about.html").read_text()
            self.assertNotIn("<script>alert(1)</script>", html)   # escaped, not injected
            self.assertIn("&lt;script&gt;", html)

    def test_cms_ui_flow(self):
        Membership.objects.create(organization=self.org, user=self.user, role=Role.OWNER)
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            url = reverse("dashboard:content", args=[self.project.id])
            self.client.force_login(self.user)
            self.client.post(url, {"action": "add_collection", "kind": "service"})
            site = pub.get_or_create_website(self.project)
            coll = site.collections.first()
            self.client.post(url, {"action": "add_item", "collection": coll.id,
                                   "title": "Consulting", "subtitle": "Expert help", "body": "We help."})
            self.client.post(url, {"action": "generate"})
            r = self.client.get(url)
            self.assertContains(r, "Consulting")
            self.assertIn(f"{coll.slug}.html", repo_for_project(self.project).list_files())


class ScheduledProbingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="o@acme.com", password="x")
        self.org = Organization.objects.create(name="Acme", created_by=self.user)
        self.project = Project.objects.create(organization=self.org, name="Acme Site", created_by=self.user)

    def test_monitor_sites_command_probes_live_sites(self):
        from django.core.management import call_command
        from io import StringIO
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            repo = repo_for_project(self.project); repo.init()
            repo.write_files({"index.html": PAGE}); repo.commit("seed")
            site = pub.get_or_create_website(self.project)
            pub.publish(site, user=self.user)          # 1 check from publish
            before = site.health_checks.count()
            out = StringIO()
            call_command("monitor_sites", stdout=out)
            self.assertIn("Checked 1 live site", out.getvalue())
            self.assertEqual(site.health_checks.count(), before + 1)   # command recorded one more


class CustomDomainRoutingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="o@acme.com", password="x")
        self.org = Organization.objects.create(name="Acme", created_by=self.user)
        self.project = Project.objects.create(organization=self.org, name="Acme Site", created_by=self.user)

    def _verified_domain(self, host="www.acme.test"):
        from apps.publishing import domain_service as dom
        from apps.publishing.domains import verify_name
        repo = repo_for_project(self.project); repo.init()
        repo.write_files({"index.html": "<html><body>Acme home</body></html>"}); repo.commit("seed")
        site = pub.get_or_create_website(self.project)
        pub.publish(site, user=self.user)
        d = dom.connect_domain(site, hostname=host, user=self.user)

        class _R:
            def available(self): return True
            def txt(self, name): return [d.verification_token]
        dom.verify_domain(d, resolver=_R())
        return site, d

    def test_verified_domain_serves_the_site(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            self._verified_domain("www.acme.test")
            r = self.client.get("/", HTTP_HOST="www.acme.test")
            self.assertEqual(r.status_code, 200)
            self.assertIn(b"Acme home", b"".join(r.streaming_content))

    def test_unverified_domain_does_not_serve(self):
        from apps.publishing import domain_service as dom
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            repo = repo_for_project(self.project); repo.init()
            repo.write_files({"index.html": "<html><body>x</body></html>"}); repo.commit("seed")
            site = pub.get_or_create_website(self.project)
            pub.publish(site, user=self.user)
            dom.connect_domain(site, hostname="pending.acme.test", user=self.user)   # not verified
            # Host doesn't match a verified domain → falls through to normal routing (not the site).
            r = self.client.get("/", HTTP_HOST="pending.acme.test")
            self.assertNotIn(b"<body>x</body>", b"".join(getattr(r, "streaming_content", [b""])))


class AcmeChallengeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="o@acme.com", password="x")
        self.org = Organization.objects.create(name="Acme", created_by=self.user)
        self.project = Project.objects.create(organization=self.org, name="Acme Site", created_by=self.user)

    def test_challenge_served_as_plain_text(self):
        from apps.publishing import domain_service as dom
        from apps.publishing.models import AcmeChallenge
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = pub.get_or_create_website(self.project)
            d = dom.connect_domain(site, hostname="www.acme.test", user=self.user)
            AcmeChallenge.objects.create(domain=d, token="tok123", key_authorization="tok123.keyauth")
            r = self.client.get("/.well-known/acme-challenge/tok123")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r["Content-Type"], "text/plain")
            self.assertEqual(r.content, b"tok123.keyauth")

    def test_unknown_challenge_404(self):
        r = self.client.get("/.well-known/acme-challenge/nope")
        self.assertEqual(r.status_code, 404)


class PaymentsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="owner@acme.com", password="x")
        self.org = Organization.objects.create(name="Acme", created_by=self.user)
        self.project = Project.objects.create(organization=self.org, name="Acme Site", created_by=self.user)

    def _site(self):
        return pub.get_or_create_website(self.project)

    def test_card_gateways_gated_manual_available(self):
        from apps.publishing import payments
        self.assertTrue(payments.get_provider("manual").is_available())
        self.assertFalse(payments.get_provider("stripe").is_available())    # no key in env
        self.assertFalse(payments.get_provider("payfast").is_available())

    def test_gateway_refuses_without_key(self):
        from apps.publishing import payments
        with self.assertRaises(payments.PaymentError) as ctx:
            payments.get_provider("stripe").start_checkout(order=None)
        self.assertIn("not configured", str(ctx.exception).lower())

    def test_order_total_computed_server_side(self):
        from apps.publishing import ecommerce_service as shop
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            p = shop.create_product(site, name="Mug", price_cents=1500, user=self.user)
            order = shop.create_order(site, items=[{"product_id": p.id, "quantity": 3}],
                                      customer_email="buyer@x.com")
            self.assertEqual(order.subtotal_cents, 4500)   # 3 × 1500, from real price
            self.assertEqual(order.items.count(), 1)

    def test_manual_checkout_then_merchant_confirms(self):
        from apps.publishing import ecommerce_service as shop
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            p = shop.create_product(site, name="Mug", price_cents=1500, user=self.user)
            order = shop.create_order(site, items=[{"product_id": p.id, "quantity": 1}])
            result = shop.start_checkout(order, provider_key="manual")
            self.assertEqual(result["mode"], "manual")
            order.refresh_from_db()
            self.assertEqual(order.status, "awaiting_payment")   # NOT paid yet
            # Only a real merchant confirmation marks it paid.
            shop.confirm_manual_payment(order, user=self.user)
            order.refresh_from_db()
            self.assertEqual(order.status, "paid")
            self.assertEqual(order.payments.filter(status="succeeded").count(), 1)

    def test_checkout_via_gateway_does_not_fake_payment(self):
        from apps.publishing import ecommerce_service as shop
        from apps.publishing.payments import PaymentError
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            p = shop.create_product(site, name="Mug", price_cents=1500, user=self.user)
            order = shop.create_order(site, items=[{"product_id": p.id, "quantity": 1}])
            with self.assertRaises(PaymentError):
                shop.start_checkout(order, provider_key="stripe")   # refuses, no fake charge
            order.refresh_from_db()
            self.assertEqual(order.status, "pending")   # unchanged — never marked paid

    def test_public_checkout_endpoint_creates_order(self):
        from apps.publishing import ecommerce_service as shop
        from apps.publishing.models import Order
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            p = shop.create_product(site, name="Mug", price_cents=1500, user=self.user)
            r = self.client.post(reverse("publishing:checkout", args=[site.subdomain]),
                                  {"product_id": p.id, "quantity": "2", "email": "b@x.com"})
            self.assertEqual(r.status_code, 200)
            self.assertIn(b"Thank you", r.content)
            order = Order.objects.get(website=site)
            self.assertEqual(order.subtotal_cents, 3000)
            self.assertEqual(order.status, "awaiting_payment")

    def test_confirmation_and_receipt_emails(self):
        from django.core import mail
        from apps.publishing import ecommerce_service as shop
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            p = shop.create_product(site, name="Mug", price_cents=1500, user=self.user)
            order = shop.create_order(site, items=[{"product_id": p.id, "quantity": 2}],
                                      customer_email="buyer@x.com")
            shop.start_checkout(order, provider_key="manual")
            order.refresh_from_db()
            self.assertTrue(order.confirmation_sent)
            buyer_mail = [m for m in mail.outbox if "buyer@x.com" in m.to]
            self.assertEqual(len(buyer_mail), 1)                # buyer confirmation sent
            self.assertIn(order.reference, buyer_mail[0].body)
            self.assertIn("2 × Mug", buyer_mail[0].body)        # line items
            shop.confirm_manual_payment(order, user=self.user)
            order.refresh_from_db()
            self.assertTrue(order.receipt_sent)
            buyer_mail = [m for m in mail.outbox if "buyer@x.com" in m.to]
            self.assertEqual(len(buyer_mail), 2)                # + receipt
            self.assertIn("Payment received", buyer_mail[1].subject)

    def test_no_email_no_send_but_order_stands(self):
        from django.core import mail
        from apps.publishing import ecommerce_service as shop
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            p = shop.create_product(site, name="Mug", price_cents=1500, user=self.user)
            order = shop.create_order(site, items=[{"product_id": p.id, "quantity": 1}])  # no email
            shop.start_checkout(order, provider_key="manual")
            order.refresh_from_db()
            self.assertFalse(order.confirmation_sent)           # honest: no buyer email sent
            self.assertNotIn("buyer", "".join(r for m in mail.outbox for r in m.to))
            self.assertEqual(order.status, "awaiting_payment")  # order still stands

    def test_inventory_reserved_on_order(self):
        from apps.publishing import ecommerce_service as shop
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            p = shop.create_product(site, name="Mug", price_cents=1500,
                                    track_inventory=True, stock=5, user=self.user)
            shop.create_order(site, items=[{"product_id": p.id, "quantity": 2}])
            p.refresh_from_db()
            self.assertEqual(p.stock, 3)     # reserved

    def test_oversell_is_prevented(self):
        from apps.publishing import ecommerce_service as shop
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            p = shop.create_product(site, name="Mug", price_cents=1500,
                                    track_inventory=True, stock=1, user=self.user)
            with self.assertRaises(shop.EcommerceError):
                shop.create_order(site, items=[{"product_id": p.id, "quantity": 3}])
            p.refresh_from_db()
            self.assertEqual(p.stock, 1)     # unchanged — transaction rolled back
            self.assertEqual(site.orders.count(), 0)

    def test_cancel_restocks(self):
        from apps.publishing import ecommerce_service as shop
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            p = shop.create_product(site, name="Mug", price_cents=1500,
                                    track_inventory=True, stock=5, user=self.user)
            order = shop.create_order(site, items=[{"product_id": p.id, "quantity": 2}])
            shop.cancel_order(order, user=self.user)
            p.refresh_from_db()
            self.assertEqual(p.stock, 5)     # returned
            # A second cancel doesn't double-restock.
            shop.cancel_order(order, user=self.user)
            p.refresh_from_db()
            self.assertEqual(p.stock, 5)

    def test_untracked_product_ignores_stock(self):
        from apps.publishing import ecommerce_service as shop
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            p = shop.create_product(site, name="Service", price_cents=9900, user=self.user)  # untracked
            shop.create_order(site, items=[{"product_id": p.id, "quantity": 99}])
            p.refresh_from_db()
            self.assertFalse(p.track_inventory)
            self.assertEqual(site.orders.count(), 1)   # no stock limit

    def test_storefront_shows_out_of_stock(self):
        from apps.publishing import ecommerce_service as shop
        from apps.publishing import storefront
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            shop.create_product(site, name="Mug", price_cents=1500,
                                track_inventory=True, stock=0, user=self.user)
            files = storefront.render_storefront(site)
            self.assertIn("Out of stock", files["shop/index.html"])
            self.assertNotIn("/checkout", files["shop/index.html"])   # no buy form when out

    def test_refund_paid_manual_order_restocks_and_emails(self):
        from django.core import mail
        from apps.publishing import ecommerce_service as shop
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            p = shop.create_product(site, name="Mug", price_cents=1500,
                                    track_inventory=True, stock=5, user=self.user)
            order = shop.create_order(site, items=[{"product_id": p.id, "quantity": 2}],
                                      customer_email="buyer@x.com")
            shop.start_checkout(order, provider_key="manual")
            shop.confirm_manual_payment(order, user=self.user)
            p.refresh_from_db(); self.assertEqual(p.stock, 3)   # sold, still reserved
            mail.outbox.clear()
            shop.refund_order(order, user=self.user, reason="Customer changed mind")
            order.refresh_from_db(); p.refresh_from_db()
            self.assertEqual(order.status, "refunded")
            self.assertEqual(order.payments.filter(status="refunded").count(), 1)
            self.assertEqual(p.stock, 5)                        # restocked
            self.assertEqual(len(mail.outbox), 1)               # buyer emailed
            self.assertIn("refunded", mail.outbox[0].body.lower())

    def test_refund_requires_paid(self):
        from apps.publishing import ecommerce_service as shop
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            p = shop.create_product(site, name="Mug", price_cents=1500, user=self.user)
            order = shop.create_order(site, items=[{"product_id": p.id, "quantity": 1}])
            with self.assertRaises(shop.EcommerceError):
                shop.refund_order(order, user=self.user)        # not paid
            shop.start_checkout(order, provider_key="manual")
            shop.confirm_manual_payment(order, user=self.user)
            shop.refund_order(order, user=self.user)
            # Double refund is a no-op.
            self.assertEqual(shop.refund_order(order, user=self.user).status, "refunded")

    def test_gateway_refund_gated(self):
        import os
        from unittest import mock
        from apps.publishing import ecommerce_service as shop
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            p = shop.create_product(site, name="Mug", price_cents=1500, user=self.user)
            order = shop.create_order(site, items=[{"product_id": p.id, "quantity": 1}])
            # Pretend a gateway order reached 'paid' (provider stripe).
            order.provider = "stripe"; order.status = "paid"; order.save()
            with self.assertRaises(shop.EcommerceError) as ctx:
                shop.refund_order(order, user=self.user)
            self.assertIn("aren't enabled", str(ctx.exception))
            order.refresh_from_db()
            self.assertEqual(order.status, "paid")              # not falsely refunded

    def test_sales_summary_counts_paid_only_and_by_currency(self):
        from apps.publishing import ecommerce_service as shop
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            mug = shop.create_product(site, name="Mug", price_cents=1500, currency="USD", user=self.user)
            cap = shop.create_product(site, name="Cap", price_cents=2000, currency="USD", user=self.user)
            # Paid order: 2 mugs + 1 cap = 5000.
            paid = shop.create_order(site, items=[{"product_id": mug.id, "quantity": 2},
                                                  {"product_id": cap.id, "quantity": 1}],
                                     customer_email="b@x.com")
            shop.start_checkout(paid, provider_key="manual")
            shop.confirm_manual_payment(paid, user=self.user)
            # An unpaid order that must NOT count as revenue.
            shop.create_order(site, items=[{"product_id": mug.id, "quantity": 5}])

            s = shop.sales_summary(site)
            self.assertEqual(s["paid_orders"], 1)
            self.assertEqual(s["units_sold"], 3)                 # only the paid order's units
            self.assertEqual(len(s["revenue"]), 1)
            self.assertEqual(s["revenue"][0]["net"], "USD 50.00")
            self.assertEqual(s["top_products"][0]["name"], "Mug")   # 2 units, most

    def test_sales_summary_nets_refunds(self):
        from apps.publishing import ecommerce_service as shop
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            p = shop.create_product(site, name="Mug", price_cents=1000, currency="USD", user=self.user)
            o1 = shop.create_order(site, items=[{"product_id": p.id, "quantity": 3}], customer_email="b@x.com")
            shop.start_checkout(o1, provider_key="manual"); shop.confirm_manual_payment(o1, user=self.user)
            o2 = shop.create_order(site, items=[{"product_id": p.id, "quantity": 1}], customer_email="b@x.com")
            shop.start_checkout(o2, provider_key="manual"); shop.confirm_manual_payment(o2, user=self.user)
            shop.refund_order(o2, user=self.user)                # refund the 1000 order
            s = shop.sales_summary(site)
            row = s["revenue"][0]
            # Gross = everything ever collected (30 + 10); refund subtracted ONCE →
            # net = money actually kept = 30. (Refund must not be double-counted.)
            self.assertEqual(row["gross"], "USD 40.00")
            self.assertEqual(row["refunded"], "USD 10.00")
            self.assertEqual(row["net"], "USD 30.00")

    def test_percent_discount_applied(self):
        from apps.publishing import ecommerce_service as shop
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            shop.create_discount(site, code="save10", kind="percent", percent_off=10, user=self.user)
            p = shop.create_product(site, name="Mug", price_cents=5000, user=self.user)
            order = shop.create_order(site, items=[{"product_id": p.id, "quantity": 1}], code="SAVE10")
            self.assertEqual(order.subtotal_cents, 5000)
            self.assertEqual(order.discount_cents, 500)
            self.assertEqual(order.total_cents, 4500)
            self.assertEqual(order.discount_code.used_count, 1)

    def test_fixed_discount_currency_must_match(self):
        from apps.publishing import ecommerce_service as shop
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            shop.create_discount(site, code="EUR5", kind="fixed", amount_off_cents=500,
                                 currency="EUR", user=self.user)
            p = shop.create_product(site, name="Mug", price_cents=5000, currency="USD", user=self.user)
            with self.assertRaises(shop.DiscountError):
                shop.create_order(site, items=[{"product_id": p.id, "quantity": 1}], code="EUR5")

    def test_min_order_and_unknown_and_maxuses(self):
        from apps.publishing import ecommerce_service as shop
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            p = shop.create_product(site, name="Mug", price_cents=1000, user=self.user)
            shop.create_discount(site, code="BIG", kind="percent", percent_off=10,
                                 min_subtotal_cents=5000, user=self.user)
            with self.assertRaises(shop.DiscountError):     # below minimum
                shop.create_order(site, items=[{"product_id": p.id, "quantity": 1}], code="BIG")
            with self.assertRaises(shop.DiscountError):     # unknown code
                shop.create_order(site, items=[{"product_id": p.id, "quantity": 1}], code="NOPE")
            shop.create_discount(site, code="ONCE", kind="percent", percent_off=5,
                                 max_uses=1, user=self.user)
            shop.create_order(site, items=[{"product_id": p.id, "quantity": 1}], code="ONCE")
            with self.assertRaises(shop.DiscountError):     # usage limit reached
                shop.create_order(site, items=[{"product_id": p.id, "quantity": 1}], code="ONCE")

    def test_checkout_shows_confirmation_with_reference(self):
        from apps.publishing import ecommerce_service as shop
        from apps.publishing.models import Order
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            p = shop.create_product(site, name="Mug", price_cents=1500, user=self.user)
            r = self.client.post(reverse("publishing:checkout", args=[site.subdomain]),
                                  {"product_id": p.id, "quantity": "1", "email": "b@x.com"})
            self.assertEqual(r.status_code, 200)
            order = Order.objects.get(website=site)
            self.assertIn(order.reference.encode(), r.content)     # reference shown
            self.assertIn(b"Thank you", r.content)

    def test_order_status_page_persistent(self):
        from apps.publishing import ecommerce_service as shop
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            p = shop.create_product(site, name="Mug", price_cents=1500, user=self.user)
            order = shop.create_order(site, items=[{"product_id": p.id, "quantity": 2}])
            shop.start_checkout(order, provider_key="manual")
            r = self.client.get(reverse("publishing:order_status", args=[site.subdomain, order.reference]))
            self.assertEqual(r.status_code, 200)
            self.assertIn(b"Mug", r.content)
            self.assertIn(b"Awaiting payment", r.content)
            # Reflects status after the merchant confirms.
            shop.confirm_manual_payment(order, user=self.user)
            r2 = self.client.get(reverse("publishing:order_status", args=[site.subdomain, order.reference]))
            self.assertIn(b"Paid", r2.content)

    def test_order_status_does_not_leak_email(self):
        from apps.publishing import ecommerce_service as shop
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            p = shop.create_product(site, name="Mug", price_cents=1500, user=self.user)
            order = shop.create_order(site, items=[{"product_id": p.id, "quantity": 1}],
                                      customer_email="private@buyer.com")
            r = self.client.get(reverse("publishing:order_status", args=[site.subdomain, order.reference]))
            self.assertNotIn(b"private@buyer.com", r.content)   # shareable URL → no PII

    def test_unknown_order_reference_404(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            r = self.client.get(reverse("publishing:order_status", args=[site.subdomain, "ORD-NOPE"]))
            self.assertEqual(r.status_code, 404)

    def test_shipping_added_to_total(self):
        from apps.publishing import ecommerce_service as shop
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            p = shop.create_product(site, name="Mug", price_cents=2000, user=self.user)
            rate = shop.create_shipping_rate(site, name="Standard", price_cents=500, user=self.user)
            order = shop.create_order(site, items=[{"product_id": p.id, "quantity": 1}],
                                      shipping_rate_id=rate.id, shipping_address="1 Main St")
            self.assertEqual(order.shipping_cents, 500)
            self.assertEqual(order.total_cents, 2500)          # 2000 + 500
            self.assertEqual(order.shipping_address, "1 Main St")

    def test_free_over_threshold(self):
        from apps.publishing import ecommerce_service as shop
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            p = shop.create_product(site, name="Mug", price_cents=6000, user=self.user)
            rate = shop.create_shipping_rate(site, name="Standard", price_cents=500,
                                             free_over_cents=5000, user=self.user)
            order = shop.create_order(site, items=[{"product_id": p.id, "quantity": 1}],
                                      shipping_rate_id=rate.id)
            self.assertEqual(order.shipping_cents, 0)          # 6000 ≥ 5000 → free
            self.assertEqual(order.total_cents, 6000)

    def test_discount_then_shipping(self):
        from apps.publishing import ecommerce_service as shop
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            p = shop.create_product(site, name="Mug", price_cents=5000, user=self.user)
            shop.create_discount(site, code="TEN", kind="percent", percent_off=10, user=self.user)
            rate = shop.create_shipping_rate(site, name="Express", price_cents=800, user=self.user)
            order = shop.create_order(site, items=[{"product_id": p.id, "quantity": 1}],
                                      code="TEN", shipping_rate_id=rate.id)
            # (5000 - 500 discount) + 800 shipping = 5300
            self.assertEqual(order.discount_cents, 500)
            self.assertEqual(order.shipping_cents, 800)
            self.assertEqual(order.total_cents, 5300)

    def test_shipping_currency_must_match(self):
        from apps.publishing import ecommerce_service as shop
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            p = shop.create_product(site, name="Mug", price_cents=2000, currency="USD", user=self.user)
            rate = shop.create_shipping_rate(site, name="Std", price_cents=500, currency="EUR", user=self.user)
            with self.assertRaises(shop.EcommerceError):
                shop.create_order(site, items=[{"product_id": p.id, "quantity": 1}],
                                  shipping_rate_id=rate.id)

    def test_tax_applied_exactly(self):
        from apps.publishing import ecommerce_service as shop
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            shop.set_tax_rate(site, name="VAT", percent="15", user=self.user)
            p = shop.create_product(site, name="Mug", price_cents=4500, user=self.user)
            order = shop.create_order(site, items=[{"product_id": p.id, "quantity": 1}])
            self.assertEqual(order.tax_cents, 675)             # 15% of 4500 = 675, exact
            self.assertEqual(order.total_cents, 5175)

    def test_tax_on_discounted_goods_plus_shipping(self):
        from apps.publishing import ecommerce_service as shop
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            shop.set_tax_rate(site, name="VAT", percent="10", user=self.user)
            shop.create_discount(site, code="TEN", kind="percent", percent_off=10, user=self.user)
            rate = shop.create_shipping_rate(site, name="Std", price_cents=500, user=self.user)
            p = shop.create_product(site, name="Mug", price_cents=5000, user=self.user)
            order = shop.create_order(site, items=[{"product_id": p.id, "quantity": 1}],
                                      code="TEN", shipping_rate_id=rate.id)
            # goods_net = 5000-500 = 4500; tax 10% of 4500 = 450; +500 shipping = 5450
            self.assertEqual(order.discount_cents, 500)
            self.assertEqual(order.tax_cents, 450)
            self.assertEqual(order.shipping_cents, 500)
            self.assertEqual(order.total_cents, 5450)

    def test_only_one_active_tax_rate(self):
        from apps.publishing import ecommerce_service as shop
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            shop.set_tax_rate(site, name="VAT", percent="15", user=self.user)
            shop.set_tax_rate(site, name="GST", percent="10", user=self.user)   # replaces
            self.assertEqual(site.tax_rates.filter(active=True).count(), 1)
            self.assertEqual(site.tax_rates.filter(active=True).first().name, "GST")

    def test_no_tax_when_none_set(self):
        from apps.publishing import ecommerce_service as shop
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            p = shop.create_product(site, name="Mug", price_cents=1000, user=self.user)
            order = shop.create_order(site, items=[{"product_id": p.id, "quantity": 1}])
            self.assertEqual(order.tax_cents, 0)
            self.assertEqual(order.total_cents, 1000)

    def test_merchant_notified_of_new_order(self):
        from django.core import mail
        from apps.publishing import ecommerce_service as shop
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()   # project owner is self.user (owner@acme.com)
            p = shop.create_product(site, name="Mug", price_cents=1500, user=self.user)
            order = shop.create_order(site, items=[{"product_id": p.id, "quantity": 1}],
                                      customer_email="buyer@x.com")
            shop.start_checkout(order, provider_key="manual")
            # Two emails: buyer confirmation + merchant new-order alert.
            recipients = [r for m in mail.outbox for r in m.to]
            self.assertIn("buyer@x.com", recipients)
            self.assertIn("owner@acme.com", recipients)
            merchant = next(m for m in mail.outbox if "owner@acme.com" in m.to)
            self.assertIn(order.reference, merchant.subject)
            self.assertIn("New order", merchant.subject)

    def test_merchant_notified_even_without_buyer_email(self):
        from django.core import mail
        from apps.publishing import ecommerce_service as shop
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            p = shop.create_product(site, name="Mug", price_cents=1500, user=self.user)
            order = shop.create_order(site, items=[{"product_id": p.id, "quantity": 1}])  # no buyer email
            shop.start_checkout(order, provider_key="manual")
            recipients = [r for m in mail.outbox for r in m.to]
            self.assertEqual(recipients, ["owner@acme.com"])   # only the merchant

    def test_cancel_releases_limited_discount_use(self):
        # Audit finding B: a cancelled (never-completed) order must return the code's use.
        from apps.publishing import ecommerce_service as shop
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = self._site()
            p = shop.create_product(site, name="Mug", price_cents=1000, user=self.user)
            shop.create_discount(site, code="ONCE", kind="percent", percent_off=10,
                                 max_uses=1, user=self.user)
            order = shop.create_order(site, items=[{"product_id": p.id, "quantity": 1}], code="ONCE")
            self.assertEqual(site.discount_codes.get(code="ONCE").used_count, 1)
            shop.cancel_order(order, user=self.user)
            self.assertEqual(site.discount_codes.get(code="ONCE").used_count, 0)   # released
            # The code works again for a real order.
            shop.create_order(site, items=[{"product_id": p.id, "quantity": 1}], code="ONCE")

    def test_store_page_renders(self):
        Membership.objects.create(organization=self.org, user=self.user, role=Role.OWNER)
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            self.client.force_login(self.user)
            r = self.client.get(reverse("dashboard:store", args=[self.project.id]))
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, "Payment methods")
            self.assertContains(r, "Not configured")   # card gateways honest


class StorefrontTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="owner@acme.com", password="x")
        self.org = Organization.objects.create(name="Acme", created_by=self.user)
        self.project = Project.objects.create(organization=self.org, name="Acme Site", created_by=self.user)

    def test_generate_emits_shop_pages_with_buy_form(self):
        from apps.publishing import ecommerce_service as shop
        from apps.publishing import storefront
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = pub.get_or_create_website(self.project)
            p = shop.create_product(site, name="Blue Mug", price_cents=1500, user=self.user)
            result = storefront.generate_storefront(site, user=self.user)
            self.assertIn("shop/index.html", result["paths"])
            self.assertIn(f"shop/{p.slug}.html", result["paths"])
            repo = repo_for_project(self.project)
            index = (repo.path / "shop/index.html").read_text()
            self.assertIn("Blue Mug", index)
            self.assertIn(f'action="/sites/{site.subdomain}/checkout"', index)   # real endpoint
            self.assertIn(f'name="product_id" value="{p.id}"', index)
            self.assertIn('lang="en"', index)                                    # accessible

    def test_storefront_has_cart_page_and_add_buttons(self):
        from apps.publishing import ecommerce_service as shop
        from apps.publishing import storefront
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = pub.get_or_create_website(self.project)
            shop.create_product(site, name="Mug", price_cents=1500, user=self.user)
            files = storefront.render_storefront(site)
            self.assertIn("shop/cart.html", files)
            self.assertIn("devforgeAdd(this)", files["shop/index.html"])       # add-to-cart button
            self.assertIn("devforge-checkout", files["shop/cart.html"])        # checkout form
            self.assertIn("i.name='line'", files["shop/cart.html"])            # JS posts line items
            self.assertIn(f'action="/sites/{site.subdomain}/checkout"', files["shop/cart.html"])

    def test_checkout_endpoint_multi_item(self):
        from apps.publishing import ecommerce_service as shop
        from apps.publishing.models import Order
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = pub.get_or_create_website(self.project)
            a = shop.create_product(site, name="Mug", price_cents=1500, user=self.user)
            b = shop.create_product(site, name="Cap", price_cents=2000, user=self.user)
            r = self.client.post(reverse("publishing:checkout", args=[site.subdomain]),
                                  {"line": [f"{a.id}:2", f"{b.id}:1"], "email": "b@x.com"})
            self.assertEqual(r.status_code, 200)
            order = Order.objects.get(website=site)
            self.assertEqual(order.items.count(), 2)
            self.assertEqual(order.subtotal_cents, 1500 * 2 + 2000)   # 5000, one order

    def test_product_image_shown_in_storefront(self):
        from apps.publishing import assets_service as assets
        from apps.publishing import ecommerce_service as shop
        from apps.publishing import storefront
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = pub.get_or_create_website(self.project)
            asset = assets.store_asset(site, filename="mug.png", data=_png_bytes(), user=self.user)
            p = shop.create_product(site, name="Mug", price_cents=1500,
                                    image_asset_id=asset.id, user=self.user)
            self.assertEqual(p.image_id, asset.id)
            files = storefront.render_storefront(site)
            self.assertIn(f'src="../{asset.path}"', files["shop/index.html"])   # relative → works live

    def test_product_image_must_belong_to_site(self):
        from apps.publishing import assets_service as assets
        from apps.publishing import ecommerce_service as shop
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = pub.get_or_create_website(self.project)
            # An asset on a DIFFERENT project/site.
            other_proj = Project.objects.create(organization=self.org, name="Other")
            other = pub.get_or_create_website(other_proj)
            foreign = assets.store_asset(other, filename="x.png", data=_png_bytes(), user=self.user)
            p = shop.create_product(site, name="Mug", price_cents=1500,
                                    image_asset_id=foreign.id, user=self.user)
            self.assertIsNone(p.image)   # cross-site asset rejected

    def test_no_products_no_storefront(self):
        from apps.publishing import storefront
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = pub.get_or_create_website(self.project)
            with self.assertRaises(storefront.StorefrontError):
                storefront.generate_storefront(site, user=self.user)

    def test_end_to_end_generate_publish_buy(self):
        from apps.publishing import ecommerce_service as shop
        from apps.publishing import storefront
        from apps.publishing.models import Order
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = pub.get_or_create_website(self.project)
            # A home page so the site has something, plus a product + storefront.
            repo = repo_for_project(self.project); repo.init()
            repo.write_files({"index.html": PAGE}); repo.commit("seed")
            p = shop.create_product(site, name="Mug", price_cents=1500, user=self.user)
            storefront.generate_storefront(site, user=self.user)
            pub.publish(site, user=self.user)
            # The published shop page really serves, and its form targets checkout.
            r = self.client.get(f"/sites/{site.subdomain}/shop/index.html")
            self.assertEqual(r.status_code, 200)
            self.assertIn(b"/checkout", b"".join(r.streaming_content))
            # Posting the buy form to the real endpoint creates an order.
            r2 = self.client.post(reverse("publishing:checkout", args=[site.subdomain]),
                                  {"product_id": p.id, "quantity": "2", "email": "b@x.com"})
            self.assertEqual(r2.status_code, 200)
            order = Order.objects.get(website=site)
            self.assertEqual(order.subtotal_cents, 3000)
            self.assertEqual(order.status, "awaiting_payment")


class StoreManagementTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="owner@acme.com", password="x")
        self.org = Organization.objects.create(name="Acme", created_by=self.user)
        Membership.objects.create(organization=self.org, user=self.user, role=Role.OWNER)
        self.project = Project.objects.create(organization=self.org, name="Acme Site", created_by=self.user)
        self.client.force_login(self.user)

    def test_edit_and_deactivate_product(self):
        from apps.publishing import ecommerce_service as shop
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = pub.get_or_create_website(self.project)
            p = shop.create_product(site, name="Mug", price_cents=1000, user=self.user)
            url = reverse("dashboard:store", args=[self.project.id])
            self.client.post(url, {"action": "edit_product", "product": p.id,
                                   "name": "Blue Mug", "price": "12.50", "stock": "0"})
            p.refresh_from_db()
            self.assertEqual(p.name, "Blue Mug")
            self.assertEqual(p.price_cents, 1250)          # units → cents
            self.client.post(url, {"action": "toggle_product", "product": p.id})
            p.refresh_from_db()
            self.assertFalse(p.active)                     # deactivated

    def test_add_and_toggle_discount_via_ui(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            pub.get_or_create_website(self.project)
            url = reverse("dashboard:store", args=[self.project.id])
            self.client.post(url, {"action": "add_discount", "code": "welcome", "kind": "percent",
                                   "percent_off": "15"})
            site = self.project.website
            dc = site.discount_codes.get()
            self.assertEqual(dc.code, "WELCOME")           # uppercased
            self.assertEqual(dc.percent_off, 15)
            self.client.post(url, {"action": "toggle_discount", "discount": dc.id})
            dc.refresh_from_db()
            self.assertFalse(dc.active)

    def test_order_detail_view(self):
        from apps.publishing import ecommerce_service as shop
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site = pub.get_or_create_website(self.project)
            p = shop.create_product(site, name="Mug", price_cents=1500, user=self.user)
            order = shop.create_order(site, items=[{"product_id": p.id, "quantity": 2}],
                                      customer_email="b@x.com")
            shop.start_checkout(order, provider_key="manual")
            url = reverse("dashboard:order_detail", args=[self.project.id, order.id])
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, order.reference)
            self.assertContains(r, "Mug")
            # Mark paid from the detail page.
            self.client.post(url, {"action": "confirm_payment"})
            order.refresh_from_db()
            self.assertEqual(order.status, "paid")


class StoreProvisionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="owner@acme.com", password="x")
        self.org = Organization.objects.create(name="Acme", created_by=self.user)
        self.project = Project.objects.create(organization=self.org, name="Candle Shop",
                                              description="An online store selling candles",
                                              created_by=self.user)

    def test_provision_sets_up_the_engine(self):
        from apps.publishing.store_provision import provision_store
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            result = provision_store(self.project, "online store selling candles", user=self.user)
            site = self.project.website
            self.assertGreaterEqual(site.products.count(), 1)      # starter catalogue
            self.assertTrue(site.shipping_rates.exists())          # default shipping
            self.assertGreaterEqual(result["storefront_pages"], 1)  # /shop generated
            self.assertIn("shop/index.html", repo_for_project(self.project).list_files())

    def test_provision_is_idempotent(self):
        from apps.publishing.store_provision import provision_store
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            provision_store(self.project, "store", user=self.user)
            n = self.project.website.products.count()
            self.assertIsNone(provision_store(self.project, "store", user=self.user))  # no-op
            self.assertEqual(self.project.website.products.count(), n)   # no duplicates

    def test_build_hook_provisions_only_for_stores(self):
        from unittest import mock
        from apps.dashboard import views
        with mock.patch.object(views, "Orchestrator") as Orch, \
             mock.patch("apps.publishing.store_provision.provision_store") as prov:
            Orch.return_value.run_ready.return_value = []
            views._start_build(self.project, "build me an online shop", self.user)
            self.assertTrue(prov.called)                 # store brief → engine wired
            prov.reset_mock()
            views._start_build(self.project, "a personal blog about hiking", self.user)
            self.assertFalse(prov.called)                # non-store brief → not wired


class CommerceApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="owner@acme.com", password="x")
        self.org = Organization.objects.create(name="Acme", created_by=self.user)
        self.project = Project.objects.create(organization=self.org, name="Acme Shop", created_by=self.user)

    def _store_with_product(self, tmp, **pk):
        from apps.publishing import ecommerce_service as shop
        site = pub.get_or_create_website(self.project)
        product = shop.create_product(site, name="Mug", price_cents=1500, user=self.user, **pk)
        return site, product

    def test_products_api_lists_active_products(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site, p = self._store_with_product(tmp)
            r = self.client.get(reverse("commerce_api:products", args=[site.subdomain]))
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["products"][0]["name"], "Mug")

    def test_checkout_api_records_channel_and_shares_inventory(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site, p = self._store_with_product(tmp, track_inventory=True, stock=20)
            # A purchase on iOS via the API.
            r = self.client.post(
                reverse("commerce_api:checkout", args=[site.subdomain]),
                {"items": [{"product_id": p.id, "quantity": 1}], "channel": "ios",
                 "email": "b@x.com"},
                content_type="application/json")
            self.assertEqual(r.status_code, 201)
            body = r.json()
            self.assertEqual(body["order"]["channel"], "ios")
            # The SAME inventory the web/android read is now 19 — one source of truth.
            p.refresh_from_db()
            self.assertEqual(p.stock, 19)
            web_view = self.client.get(reverse("commerce_api:products", args=[site.subdomain]))
            self.assertEqual(web_view.json()["products"][0]["stock"], 19)

    def test_order_status_api(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site, p = self._store_with_product(tmp)
            r = self.client.post(
                reverse("commerce_api:checkout", args=[site.subdomain]),
                {"items": [{"product_id": p.id, "quantity": 2}], "channel": "android"},
                content_type="application/json")
            ref = r.json()["order"]["reference"]
            s = self.client.get(reverse("commerce_api:order", args=[site.subdomain, ref]))
            self.assertEqual(s.status_code, 200)
            self.assertEqual(s.json()["total_cents"], 3000)
            self.assertEqual(s.json()["channel"], "android")

    def test_web_and_api_orders_share_one_admin(self):
        from apps.publishing import ecommerce_service as shop
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            site, p = self._store_with_product(tmp)
            web = shop.create_order(site, items=[{"product_id": p.id, "quantity": 1}], channel="web")
            self.client.post(reverse("commerce_api:checkout", args=[site.subdomain]),
                             {"items": [{"product_id": p.id, "quantity": 1}], "channel": "ios"},
                             content_type="application/json")
            channels = set(site.orders.values_list("channel", flat=True))
            self.assertEqual(channels, {"web", "ios"})   # one order table, all channels


class PublishUITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="o@acme.com", password="x")
        self.org = Organization.objects.create(name="Acme", created_by=self.user)
        Membership.objects.create(organization=self.org, user=self.user, role=Role.OWNER)
        self.project = Project.objects.create(organization=self.org, name="Acme Site", created_by=self.user)
        self.client.force_login(self.user)

    def test_enable_then_publish_flow(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            repo = repo_for_project(self.project); repo.init()
            repo.write_files({"index.html": PAGE}); repo.commit("seed")
            url = reverse("dashboard:publish_center", args=[self.project.id])
            self.client.post(url, {"action": "enable_website"})
            self.client.post(url, {"action": "publish"})
            r = self.client.get(url)
            self.assertContains(r, "Release Center")
            self.assertContains(r, "v1.0.0")
            self.assertContains(r, "/sites/")

    def test_connect_domain_shows_dns_records(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
            url = reverse("dashboard:publish_center", args=[self.project.id])
            self.client.post(url, {"action": "enable_website"})
            self.client.post(url, {"action": "connect_domain", "hostname": "www.acme.com"})
            r = self.client.get(url)
            self.assertContains(r, "www.acme.com")
            self.assertContains(r, "_devforge-verify.www.acme.com")
            self.assertContains(r, "Pending verification")

    def test_admin_websites_page(self):
        staff = User.objects.create_user(email="s@devforge.local", password="x", is_staff=True)
        self.client.force_login(staff)
        r = self.client.get(reverse("console:websites"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Hosting targets")
        self.assertContains(r, "Not configured")
        self.assertContains(r, "Custom domains")
