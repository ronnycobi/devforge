from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from apps.organizations.models import Organization, Role
from apps.projects.models import Project
from apps.workspaces.models import Environment, Workspace

User = get_user_model()


class WorkspaceModelTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(organization=self.org, name="App")

    def test_slug_scoped_per_project(self):
        w = Workspace.objects.create(project=self.project, name="Staging")
        self.assertEqual(w.slug, "staging")
        self.assertEqual(w.environment, Environment.DEVELOPMENT)

    def test_only_one_default_workspace_per_project(self):
        Workspace.objects.create(project=self.project, name="Main", is_default=True)
        with self.assertRaises(IntegrityError):
            Workspace.objects.create(
                project=self.project, name="Other", is_default=True
            )

    def test_organization_property_traverses_project(self):
        w = Workspace.objects.create(project=self.project, name="Main")
        self.assertEqual(w.organization, self.org)


class WorkspaceAPITests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(email="alice@x.com", password="pw12345!")
        self.bob = User.objects.create_user(email="bob@x.com", password="pw12345!")

        self.org_a = Organization.objects.create(name="Org A")
        self.org_b = Organization.objects.create(name="Org B")
        self.org_a.add_member(self.alice, role=Role.OWNER)
        self.org_b.add_member(self.bob, role=Role.OWNER)

        self.proj_a = Project.objects.create(organization=self.org_a, name="A")
        self.proj_a.ensure_default_workspace()
        self.proj_b = Project.objects.create(organization=self.org_b, name="B")

    def _url(self, project):
        return reverse("projects:workspace-list", args=[project.id])

    def test_list_workspaces_of_own_project(self):
        self.client.force_login(self.alice)
        resp = self.client.get(self._url(self.proj_a))
        self.assertEqual(resp.status_code, 200)
        names = [w["name"] for w in resp.json()]
        self.assertEqual(names, ["Main"])

    def test_cannot_list_foreign_project_workspaces(self):
        self.client.force_login(self.alice)
        resp = self.client.get(self._url(self.proj_b))
        self.assertEqual(resp.status_code, 404)

    def test_create_workspace_in_own_project(self):
        self.client.force_login(self.alice)
        resp = self.client.post(
            self._url(self.proj_a),
            {"name": "Staging", "environment": "staging"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body["slug"], "staging")
        self.assertEqual(body["project"], self.proj_a.id)
        self.assertFalse(body["is_default"])

    def test_cannot_create_workspace_in_foreign_project(self):
        self.client.force_login(self.alice)
        resp = self.client.post(
            self._url(self.proj_b),
            {"name": "Sneaky"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(self.proj_b.workspaces.count(), 0)
