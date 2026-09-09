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
