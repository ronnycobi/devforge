import io
import json
import zipfile

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.exporter.service import build_export
from apps.organizations.models import Organization, Role
from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.projects.models import Project

User = get_user_model()


def _seed(project):
    ctx = ProjectContext(project)
    ctx.set(ContextKind.REQUIREMENT, "login", title="Login", content="Email login")
    ctx.set(
        ContextKind.API,
        "post-tasks",
        title="POST /api/v1/tasks/",
        content="Create a task",
        data={"method": "POST", "path": "/api/v1/tasks/", "module": "tasks"},
    )
    ctx.set(
        ContextKind.SCHEMA,
        "task",
        title="Task",
        content="A unit of work",
        data={"fields": [{"name": "title", "type": "text"}], "relations": []},
    )


class BuildExportTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(organization=self.org, name="App")
        _seed(self.project)

    def _zip(self):
        _, data = build_export(self.project)
        return zipfile.ZipFile(io.BytesIO(data))

    def test_archive_contains_expected_files(self):
        names = set(self._zip().namelist())
        self.assertIn("README.md", names)
        self.assertIn("docs/requirements.md", names)
        self.assertIn("docs/api.md", names)
        self.assertIn("api-spec.json", names)
        self.assertIn("data-model.json", names)
        self.assertIn(".env.example", names)

    def test_docs_contain_context_content(self):
        z = self._zip()
        self.assertIn("Email login", z.read("docs/requirements.md").decode())

    def test_api_spec_is_valid_json(self):
        z = self._zip()
        spec = json.loads(z.read("api-spec.json"))
        self.assertEqual(spec[0]["method"], "POST")
        self.assertEqual(spec[0]["path"], "/api/v1/tasks/")

    def test_data_model_is_valid_json(self):
        z = self._zip()
        models = json.loads(z.read("data-model.json"))
        self.assertEqual(models[0]["name"], "Task")
        self.assertEqual(models[0]["fields"][0]["name"], "title")

    def test_includes_git_tracked_source(self):
        import tempfile
        from unittest import mock

        from apps.repositories.service import ProjectRepo

        with tempfile.TemporaryDirectory() as tmp:
            repo = ProjectRepo(f"{tmp}/repo").init()
            repo.write_files({"app.py": "print('hi')"})
            repo.commit("init")
            with mock.patch(
                "apps.exporter.service.repo_for_project", return_value=repo
            ):
                names = set(self._zip().namelist())
        self.assertIn("source/app.py", names)


class ExportAPITests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(email="alice@x.com", password="pw12345!")
        self.bob = User.objects.create_user(email="bob@x.com", password="pw12345!")
        self.org_a = Organization.objects.create(name="Org A")
        self.org_b = Organization.objects.create(name="Org B")
        self.org_a.add_member(self.alice, role=Role.OWNER)
        self.org_b.add_member(self.bob, role=Role.OWNER)
        self.proj_a = Project.objects.create(organization=self.org_a, name="A")
        _seed(self.proj_a)
        self.proj_b = Project.objects.create(organization=self.org_b, name="B")

    def test_member_can_download(self):
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("exporter:export", args=[self.proj_a.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/zip")
        self.assertIn("attachment", resp["Content-Disposition"])
        zipfile.ZipFile(io.BytesIO(resp.content))  # valid zip

    def test_requires_auth(self):
        resp = self.client.get(reverse("exporter:export", args=[self.proj_a.id]))
        self.assertEqual(resp.status_code, 403)

    def test_cannot_export_foreign_project(self):
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("exporter:export", args=[self.proj_b.id]))
        self.assertEqual(resp.status_code, 404)
