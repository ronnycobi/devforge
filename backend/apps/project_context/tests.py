from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.organizations.models import Organization, Role
from apps.project_context.models import ContextEntry, ContextKind
from apps.project_context.services import ProjectContext
from apps.projects.models import Project

User = get_user_model()


class ProjectContextServiceTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(organization=self.org, name="App")
        self.ctx = ProjectContext(self.project)

    def test_set_upserts_by_kind_and_key(self):
        self.ctx.set(
            ContextKind.TECH_DECISION, "database", content="PostgreSQL"
        )
        self.ctx.set(
            ContextKind.TECH_DECISION, "database", content="PostgreSQL 16, chosen for JSONB"
        )
        entries = self.ctx.by_kind(ContextKind.TECH_DECISION)
        self.assertEqual(entries.count(), 1)  # updated, not duplicated
        self.assertIn("JSONB", entries.first().content)

    def test_add_appends_with_unique_keys(self):
        a = self.ctx.add(ContextKind.KNOWN_ISSUE, title="Slow query on tasks")
        b = self.ctx.add(ContextKind.KNOWN_ISSUE, title="Slow query on tasks")
        self.assertNotEqual(a.key, b.key)
        self.assertEqual(self.ctx.by_kind(ContextKind.KNOWN_ISSUE).count(), 2)

    def test_get_and_remove(self):
        self.ctx.set(ContextKind.NOTE, "welcome", content="hi")
        self.assertIsNotNone(self.ctx.get(ContextKind.NOTE, "welcome"))
        self.ctx.remove(ContextKind.NOTE, "welcome")
        self.assertIsNone(self.ctx.get(ContextKind.NOTE, "welcome"))

    def test_digest_groups_and_bounds(self):
        self.ctx.set(ContextKind.REQUIREMENT, "auth", title="Auth", content="Email login")
        self.ctx.set(
            ContextKind.TECH_DECISION, "db", title="Database", content="PostgreSQL"
        )
        digest = self.ctx.digest()
        self.assertIn("# Project context: App", digest)
        self.assertIn("## Requirement", digest)
        self.assertIn("Email login", digest)

        long = "x" * 10_000
        self.ctx.set(ContextKind.NOTE, "big", title="Big", content=long)
        bounded = self.ctx.digest(max_chars=500)
        self.assertLessEqual(len(bounded), 500)


class ContextAPITests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(email="alice@x.com", password="pw12345!")
        self.carol = User.objects.create_user(email="carol@x.com", password="pw12345!")
        self.bob = User.objects.create_user(email="bob@x.com", password="pw12345!")

        self.org_a = Organization.objects.create(name="Org A")
        self.org_b = Organization.objects.create(name="Org B")
        self.org_a.add_member(self.alice, role=Role.OWNER)
        self.org_a.add_member(self.carol, role=Role.MEMBER)
        self.org_b.add_member(self.bob, role=Role.OWNER)

        self.proj_a = Project.objects.create(organization=self.org_a, name="A")
        self.proj_b = Project.objects.create(organization=self.org_b, name="B")

    def _list_url(self, project):
        return reverse("project_context:list", args=[project.id])

    def test_member_can_read_context(self):
        ProjectContext(self.proj_a).set(ContextKind.NOTE, "n1", content="visible")
        self.client.force_login(self.carol)
        resp = self.client.get(self._list_url(self.proj_a))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 1)

    def test_manager_creates_entry_with_auto_key(self):
        self.client.force_login(self.alice)
        resp = self.client.post(
            self._list_url(self.proj_a),
            {"kind": "requirement", "title": "User login"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()["key"], "user-login")

    def test_member_cannot_write(self):
        self.client.force_login(self.carol)
        resp = self.client.post(
            self._list_url(self.proj_a),
            {"kind": "note", "title": "x"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_duplicate_key_rejected(self):
        ProjectContext(self.proj_a).set(ContextKind.TECH_DECISION, "db", content="pg")
        self.client.force_login(self.alice)
        resp = self.client.post(
            self._list_url(self.proj_a),
            {"kind": "tech_decision", "key": "db", "title": "Database"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_cannot_read_foreign_project_context(self):
        self.client.force_login(self.alice)
        resp = self.client.get(self._list_url(self.proj_b))
        self.assertEqual(resp.status_code, 404)

    def test_filter_by_kind(self):
        ctx = ProjectContext(self.proj_a)
        ctx.set(ContextKind.NOTE, "n", content="note")
        ctx.set(ContextKind.REQUIREMENT, "r", content="req")
        self.client.force_login(self.alice)
        resp = self.client.get(self._list_url(self.proj_a) + "?kind=requirement")
        self.assertEqual(len(resp.json()), 1)
        self.assertEqual(resp.json()[0]["kind"], "requirement")

    def test_digest_endpoint(self):
        ProjectContext(self.proj_a).set(
            ContextKind.REQUIREMENT, "auth", title="Auth", content="Email login"
        )
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("project_context:digest", args=[self.proj_a.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Email login", resp.json()["digest"])

    def test_manager_can_delete_member_cannot(self):
        entry = ProjectContext(self.proj_a).set(ContextKind.NOTE, "n", content="x")
        url = reverse("project_context:detail", args=[entry.id])

        self.client.force_login(self.carol)
        self.assertEqual(self.client.delete(url).status_code, 403)

        self.client.force_login(self.alice)
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertFalse(ContextEntry.objects.filter(id=entry.id).exists())
