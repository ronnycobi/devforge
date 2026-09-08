from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.organizations.models import Organization, Role
from apps.orchestrator.models import AgentTask
from apps.projects.models import Project

User = get_user_model()


class DashboardUITests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="o@x.com", password="pw12345!")
        self.member = User.objects.create_user(email="m@x.com", password="pw12345!")
        self.outsider = User.objects.create_user(email="z@x.com", password="pw12345!")
        self.org = Organization.objects.create(name="Acme")
        self.org.add_member(self.owner, role=Role.OWNER)
        self.org.add_member(self.member, role=Role.MEMBER)
        self.project = Project.objects.create(organization=self.org, name="App")

    def test_login_required(self):
        resp = self.client.get(reverse("dashboard:home"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp.url)

    def test_dashboard_lists_member_projects(self):
        self.client.force_login(self.member)
        resp = self.client.get(reverse("dashboard:home"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "App")

    def test_owner_creates_project_via_ui(self):
        self.client.force_login(self.owner)
        resp = self.client.post(
            reverse("dashboard:projects"),
            {"action": "create_project", "name": "New Site", "organization": self.org.id},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Project.objects.filter(name="New Site").exists())

    def test_member_cannot_create_project(self):
        self.client.force_login(self.member)
        self.client.post(
            reverse("dashboard:projects"),
            {"action": "create_project", "name": "Nope", "organization": self.org.id},
        )
        self.assertFalse(Project.objects.filter(name="Nope").exists())

    def test_overview_and_key_pages_render(self):
        self.client.force_login(self.member)
        for name in ["home", "projects", "agents", "tasks", "deployments", "usage"]:
            self.assertEqual(self.client.get(reverse("dashboard:" + name)).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("dashboard:soon", args=["monitoring"])).status_code, 200
        )

    def test_project_workspace_renders(self):
        self.client.force_login(self.member)
        resp = self.client.get(reverse("dashboard:project", args=[self.project.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Technology stack")
        self.assertContains(resp, "Agent tasks")

    def test_owner_queues_task_via_ui(self):
        self.client.force_login(self.owner)
        self.client.post(
            reverse("dashboard:project", args=[self.project.id]),
            {"action": "create_task", "agent_key": "requirements", "brief": "x"},
        )
        self.assertEqual(
            AgentTask.objects.filter(project=self.project, agent_key="requirements").count(), 1
        )

    def test_owner_selects_stack_via_ui(self):
        self.client.force_login(self.owner)
        self.client.post(
            reverse("dashboard:project", args=[self.project.id]),
            {"action": "select_stack", "backend": "django", "frontend": "react"},
        )
        self.project.refresh_from_db()
        self.assertEqual(self.project.technology["backend"], "django")
        self.assertEqual(self.project.technology["frontend"], "react")

    def test_cannot_open_foreign_project(self):
        self.client.force_login(self.outsider)
        resp = self.client.get(reverse("dashboard:project", args=[self.project.id]))
        self.assertEqual(resp.status_code, 404)


class SecurityPageTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="so@x.com", password="pw12345!")
        self.member = User.objects.create_user(email="sm@x.com", password="pw12345!")
        self.org = Organization.objects.create(name="Acme")
        self.org.add_member(self.owner, role=Role.OWNER)
        self.org.add_member(self.member, role=Role.MEMBER)
        self.project = Project.objects.create(organization=self.org, name="App")

    def test_page_lists_projects(self):
        self.client.force_login(self.member)
        resp = self.client.get(reverse("dashboard:security"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "App")

    def test_owner_runs_scan_and_findings_appear(self):
        import tempfile
        from django.test import override_settings
        from apps.repositories.service import repo_for_project
        from apps.project_context.models import ContextEntry, ContextKind

        self.client.force_login(self.owner)
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                repo = repo_for_project(self.project)
                repo.init()
                repo.write_files({"app.py": "API_KEY = 'sk-live-abc123456'\nx = eval(v)\n"})
                repo.commit("seed")
                resp = self.client.post(
                    reverse("dashboard:security"),
                    {"action": "run_scan", "project": self.project.id},
                    follow=True,
                )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            ContextEntry.objects.filter(project=self.project, kind=ContextKind.SECURITY).exists()
        )

    def test_member_cannot_run_scan(self):
        self.client.force_login(self.member)
        resp = self.client.post(
            reverse("dashboard:security"),
            {"action": "run_scan", "project": self.project.id},
            follow=True,
        )
        self.assertContains(resp, "Owner or admin")
