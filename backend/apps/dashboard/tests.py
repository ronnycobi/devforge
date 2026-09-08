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


class PeopleUITests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="po@x.com", password="pw12345!")
        self.member = User.objects.create_user(email="pm@x.com", password="pw12345!")
        self.org = Organization.objects.create(name="Acme")
        self.org.add_member(self.owner, role=Role.OWNER)
        self.org.add_member(self.member, role=Role.MEMBER)

    def test_page_lists_members(self):
        self.client.force_login(self.member)
        resp = self.client.get(reverse("dashboard:people"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "po@x.com")

    def test_owner_invites_and_link_shown(self):
        from apps.organizations.models import Invitation
        self.client.force_login(self.owner)
        resp = self.client.post(
            reverse("dashboard:people"),
            {"action": "invite", "organization": self.org.id,
             "email": "new@x.com", "role": "admin"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        inv = Invitation.objects.get(email="new@x.com", organization=self.org)
        self.assertContains(resp, inv.token)  # accept link surfaced

    def test_member_cannot_invite(self):
        self.client.force_login(self.member)
        resp = self.client.post(
            reverse("dashboard:people"),
            {"action": "invite", "organization": self.org.id, "email": "x@x.com"},
            follow=True,
        )
        self.assertContains(resp, "Owner or admin")

    def test_owner_creates_team(self):
        from apps.organizations.models import Team
        self.client.force_login(self.owner)
        self.client.post(
            reverse("dashboard:people"),
            {"action": "create_team", "organization": self.org.id, "name": "Platform"},
        )
        self.assertTrue(Team.objects.filter(organization=self.org, name="Platform").exists())

    def test_accept_invite_flow(self):
        from apps.organizations import invitations
        invite = invitations.create_invitation(self.org, "joiner@x.com", invited_by=self.owner)
        joiner = User.objects.create_user(email="joiner@x.com", password="pw12345!")
        self.client.force_login(joiner)
        resp = self.client.get(reverse("dashboard:accept_invite", args=[invite.token]), follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            self.org.memberships.filter(user=joiner).exists()  # membership created
        )


class RealPagesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="rp@x.com", password="pw12345!")
        self.org = Organization.objects.create(name="Acme")
        self.org.add_member(self.user, role=Role.OWNER)
        Project.objects.create(organization=self.org, name="App", created_by=self.user)
        self.client.force_login(self.user)

    def test_all_former_soon_links_render_real_pages(self):
        named = ["templates", "repository", "settings"]
        for name in named:
            r = self.client.get(reverse(f"dashboard:{name}"))
            self.assertEqual(r.status_code, 200, name)
            self.assertNotContains(r, "coming soon")
        for slug in ["apis", "database", "tests", "code-issues"]:
            r = self.client.get(reverse("dashboard:section", args=[slug]))
            self.assertEqual(r.status_code, 200, slug)
            self.assertNotContains(r, "coming soon")
        for area in ["environments", "cloud", "logs", "monitoring", "incidents",
                     "scaling", "performance", "infrastructure", "modernization"]:
            r = self.client.get(reverse("dashboard:ops", args=[area]))
            self.assertEqual(r.status_code, 200, area)
            self.assertNotContains(r, "coming soon")

    def test_settings_rename_and_delete(self):
        p = Project.objects.create(organization=self.org, name="Temp", created_by=self.user)
        self.client.post(reverse("dashboard:settings"),
                         {"action": "rename", "project": p.id, "name": "Renamed", "description": "d"})
        p.refresh_from_db()
        self.assertEqual(p.name, "Renamed")
        self.client.post(reverse("dashboard:settings"), {"action": "delete", "project": p.id})
        self.assertFalse(Project.objects.filter(pk=p.id).exists())

    def test_unknown_section_404(self):
        self.assertEqual(self.client.get(reverse("dashboard:section", args=["nope"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("dashboard:ops", args=["nope"])).status_code, 404)


class MachineryLeakGuardTests(TestCase):
    """The customer dashboard must not expose the internal agent machinery."""
    def setUp(self):
        self.user = User.objects.create_user(email="lg@x.com", password="pw12345!")
        self.org = Organization.objects.create(name="Acme")
        self.org.add_member(self.user, role=Role.OWNER)
        self.project = Project.objects.create(organization=self.org, name="App", created_by=self.user)
        self.client.force_login(self.user)

    def test_ai_page_hides_capabilities_and_topology(self):
        r = self.client.get(reverse("dashboard:agents"))
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        for term in ["write_backend", "use_sandbox", "review_code", "write_migrations",
                     "use_repository", "least-privilege", "orchestrat", "capability"]:
            self.assertNotIn(term, body, term)

    def test_project_page_has_no_agent_roster_picker(self):
        body = self.client.get(reverse("dashboard:project", args=[self.project.id])).content.decode()
        self.assertNotIn('name="agent_key"', body)  # no roster dropdown
        for term in ["write_backend", "use_sandbox", "least-privilege"]:
            self.assertNotIn(term, body, term)
