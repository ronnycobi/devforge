from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.organizations.models import Organization
from apps.projects.models import Project
from apps.skills import service
from apps.skills.models import Skill


class SelectionTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(organization=self.org, name="Shop")

    def test_builtin_matches_by_keyword(self):
        picked = service.select_skills("Build an online store to sell candles")
        slugs = {p["slug"] for p in picked}
        self.assertIn("ecommerce", slugs)
        self.assertNotIn("blog", slugs)

    def test_no_match_is_empty(self):
        self.assertEqual(service.select_skills("a quiet brochure page about us"), [])

    def test_guidance_text_includes_body(self):
        _skills, text = service.guidance_for("a crm for my leads")
        self.assertIn("CRM", text)
        self.assertIn("pipeline", text.lower())

    def test_org_scoped_skill_only_for_its_org(self):
        other = Organization.objects.create(name="Other")
        Skill.objects.create(name="Acme playbook", slug="acme-pb", keywords=["widget"],
                             body="Acme does widgets thus.", scope=Skill.SCOPE_ORG, organization=self.org)
        # Visible to Acme…
        self.assertTrue(any(p["slug"] == "acme-pb"
                            for p in service.select_skills("a widget app", organization=self.org)))
        # …but not to another org.
        self.assertFalse(any(p["slug"] == "acme-pb"
                             for p in service.select_skills("a widget app", organization=other)))

    def test_apply_records_context_and_audit(self):
        from apps.project_context.models import ContextKind
        from apps.project_context.services import ProjectContext
        applied = service.apply_to_project(self.project, "an online shop with a cart")
        self.assertTrue(any(s["slug"] == "ecommerce" for s in applied))
        note = ProjectContext(self.project).by_kind(ContextKind.NOTE).filter(key="applied-skills").first()
        self.assertIsNotNone(note)
        self.assertIn("commerce engine", note.content)


class SkillsAdminPageTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(email="s@devforge.local", password="x", is_staff=True)

    def test_page_lists_builtins_and_can_add(self):
        self.client.force_login(self.staff)
        r = self.client.get(reverse("console:skills"))
        self.assertContains(r, "E-commerce store")     # a builtin
        self.client.post(reverse("console:skills"),
                         {"name": "Restaurant menu", "keywords": "menu, restaurant", "body": "Model a menu."})
        s = Skill.objects.get(slug="restaurant-menu")
        self.assertEqual(s.scope, "global")
        self.assertEqual(s.keywords, ["menu", "restaurant"])
