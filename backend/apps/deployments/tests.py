import tempfile

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.deployments.models import DeploymentStatus
from apps.deployments.service import approve, request_deploy, run
from apps.organizations.models import Organization, Role
from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.projects.models import Project

User = get_user_model()


def _seed(project):
    ProjectContext(project).set(
        ContextKind.REQUIREMENT, "x", title="X", content="something to export"
    )


class RequestTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(organization=self.org, name="App")

    def test_nonprod_is_pending(self):
        d = request_deploy(project=self.project, environment="development", provider="local")
        self.assertEqual(d.status, DeploymentStatus.PENDING)

    def test_production_waits_for_approval(self):
        d = request_deploy(project=self.project, environment="production", provider="local")
        self.assertEqual(d.status, DeploymentStatus.WAITING_FOR_APPROVAL)


class RunTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(organization=self.org, name="App")
        _seed(self.project)

    def test_local_dev_deploy_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                d = request_deploy(
                    project=self.project, environment="development", provider="local"
                )
                run(d)
        self.assertEqual(d.status, DeploymentStatus.SUCCEEDED)
        self.assertTrue(d.url.startswith("file://"))
        self.assertIn("wrote", d.log)

    def test_production_without_approval_is_refused(self):
        d = request_deploy(project=self.project, environment="production", provider="local")
        run(d)
        self.assertEqual(d.status, DeploymentStatus.FAILED)
        self.assertIn("requires approval", d.log)

    def test_production_after_approval_succeeds(self):
        approver = User.objects.create_user(email="boss@x.com", password="pw12345!")
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                d = request_deploy(
                    project=self.project, environment="production", provider="local"
                )
                approve(d, approver)
                run(d)
        self.assertEqual(d.status, DeploymentStatus.SUCCEEDED)
        self.assertTrue(d.approved)

    def test_unavailable_provider_fails(self):
        d = request_deploy(project=self.project, environment="development", provider="aws")
        run(d)
        self.assertEqual(d.status, DeploymentStatus.FAILED)
        self.assertIn("unavailable", d.log)


class DeploymentAPITests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(email="alice@x.com", password="pw12345!")
        self.carol = User.objects.create_user(email="carol@x.com", password="pw12345!")
        self.org = Organization.objects.create(name="Acme")
        self.org.add_member(self.alice, role=Role.OWNER)
        self.org.add_member(self.carol, role=Role.MEMBER)
        self.project = Project.objects.create(organization=self.org, name="App")
        _seed(self.project)
        self.foreign = Project.objects.create(
            organization=Organization.objects.create(name="Other"), name="B"
        )

    def _list_url(self, project):
        return reverse("deployments:list", args=[project.id])

    def test_owner_creates_deployment(self):
        self.client.force_login(self.alice)
        resp = self.client.post(
            self._list_url(self.project),
            {"environment": "staging", "provider": "local"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()["status"], "pending")

    def test_member_cannot_create(self):
        self.client.force_login(self.carol)
        resp = self.client.post(
            self._list_url(self.project),
            {"environment": "staging", "provider": "local"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_bad_environment_rejected(self):
        self.client.force_login(self.alice)
        resp = self.client.post(
            self._list_url(self.project),
            {"environment": "prod-oops", "provider": "local"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_approve_and_run_production_via_api(self):
        self.client.force_login(self.alice)
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                created = self.client.post(
                    self._list_url(self.project),
                    {"environment": "production", "provider": "local"},
                    content_type="application/json",
                ).json()
                self.assertEqual(created["status"], "waiting_for_approval")
                dep_id = created["id"]
                # run before approval -> refused
                r1 = self.client.post(reverse("deployments:run", args=[dep_id]))
                self.assertEqual(r1.json()["status"], "failed")
                # approve, then run -> succeeds
                self.client.post(reverse("deployments:approve", args=[dep_id]))
                r2 = self.client.post(reverse("deployments:run", args=[dep_id]))
        self.assertEqual(r2.json()["status"], "succeeded")

    def test_cannot_deploy_foreign_project(self):
        self.client.force_login(self.alice)
        resp = self.client.get(self._list_url(self.foreign))
        self.assertEqual(resp.status_code, 404)
