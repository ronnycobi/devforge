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

    def test_admin_websites_page(self):
        staff = User.objects.create_user(email="s@devforge.local", password="x", is_staff=True)
        self.client.force_login(staff)
        r = self.client.get(reverse("console:websites"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Hosting targets")
        self.assertContains(r, "Not configured")
