"""The preview runner really serves a project's files over a localhost port."""
import tempfile

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.organizations.models import Organization, Role
from apps.preview_runner.runner import PreviewError, runner
from apps.projects.models import Project
from apps.repositories.service import repo_for_project


class PreviewRunnerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="pr@x.com", password="pw12345!")
        self.org = Organization.objects.create(name="Acme")
        self.org.add_member(self.user, role=Role.OWNER)
        self.project = Project.objects.create(organization=self.org, name="Site", created_by=self.user)

    def _seed(self, tmp):
        repo = repo_for_project(self.project)
        repo.init()
        repo.write_files({"index.html": "<h1>Hello from DevForge</h1>"})
        repo.commit("seed")

    def test_start_serves_files_then_stop(self):
        import urllib.request
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                self._seed(tmp)
                pv = runner.start_static(self.project)
                try:
                    self.assertTrue(pv.alive)
                    body = urllib.request.urlopen(f"http://127.0.0.1:{pv.port}/", timeout=5).read()
                    self.assertIn(b"Hello from DevForge", body)
                finally:
                    runner.stop(self.project.id)
                self.assertIsNone(runner.get(self.project.id))  # stopped

    def test_start_without_files_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                with self.assertRaises(PreviewError):
                    runner.start_static(self.project)  # no repo/files yet

    def test_proxy_serves_running_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                self._seed(tmp)
                runner.start_static(self.project)
                try:
                    self.client.force_login(self.user)
                    r = self.client.get(reverse("dashboard:preview_live", args=[self.project.id]))
                    self.assertEqual(r.status_code, 200)
                    self.assertIn(b"Hello from DevForge", r.content)
                finally:
                    runner.stop(self.project.id)

    def test_proxy_404_when_not_running(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse("dashboard:preview_live", args=[self.project.id]))
        self.assertEqual(r.status_code, 404)
