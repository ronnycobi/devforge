from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.technology.registry import Category, CodegenStatus, registry
from apps.technology.stacks import backend_stacks, get_stack

User = get_user_model()


class RegistryTests(SimpleTestCase):
    def test_catalog_spans_many_languages_and_frameworks(self):
        langs = {t.id for t in registry.by_category(Category.LANGUAGE)}
        self.assertTrue({"python", "go", "typescript", "rust", "java"} <= langs)
        fwks = {t.id for t in registry.by_category(Category.FRAMEWORK)}
        self.assertTrue({"django", "fastapi", "nextjs", "spring_boot", "flutter"} <= fwks)

    def test_frameworks_for_language(self):
        py = {t.id for t in registry.frameworks_for("python")}
        self.assertEqual(py, {"django", "fastapi", "flask"})

    def test_django_is_supported_others_planned(self):
        self.assertEqual(registry.get("django").codegen, CodegenStatus.SUPPORTED)
        self.assertEqual(registry.get("nextjs").codegen, CodegenStatus.PLANNED)

    def test_frontend_catalog_includes_the_major_frameworks(self):
        options = {t.id for t in registry.options_for_role("frontend")}
        self.assertTrue(
            {"react", "vue", "angular", "svelte", "sveltekit", "nextjs", "nuxt"}
            <= options
        )

    def test_mobile_and_testing_and_deployment_expanded(self):
        mobile = {t.id for t in registry.options_for_role("mobile")}
        self.assertTrue({"flutter", "react_native", "swiftui"} <= mobile)
        testing = {t.id for t in registry.by_category(Category.TESTING)}
        self.assertTrue({"pytest", "jest", "vitest", "junit"} <= testing)


class StackTests(SimpleTestCase):
    def test_runnable_stacks_registered(self):
        ids = {s.id for s in backend_stacks()}
        self.assertEqual(ids, {"python-stdlib", "django", "fastapi", "node", "go"})

    def test_go_stack_runnable_only_when_toolchain_present(self):
        import shutil

        self.assertEqual(get_stack("go").is_runnable(), shutil.which("go") is not None)

    def test_python_stacks_are_runnable(self):
        self.assertTrue(get_stack("django").is_runnable())
        self.assertTrue(get_stack("python-stdlib").is_runnable())
        self.assertTrue(get_stack("fastapi").is_runnable())  # fastapi installed

    def test_node_stack_runnable_when_node_present(self):
        import shutil

        self.assertEqual(get_stack("node").is_runnable(), shutil.which("node") is not None)

    def test_django_scaffolds_stdlib_does_not(self):
        dj = get_stack("django").build_project("shop", [{"path": "models.py", "content": "x=1\n"}])
        paths = {f["path"] for f in dj}
        self.assertIn("manage.py", paths)
        self.assertIn("shop/models.py", paths)

        flat = get_stack("python-stdlib").build_project(None, [{"path": "app.py", "content": "x=1\n"}])
        self.assertEqual([f["path"] for f in flat], ["app.py"])

    def test_unknown_stack_returns_none(self):
        self.assertIsNone(get_stack("cobol"))


class StackSelectionTests(TestCase):
    def setUp(self):
        from apps.organizations.models import Organization, Role
        from apps.projects.models import Project

        self.owner = User.objects.create_user(email="o@x.com", password="pw12345!")
        self.member = User.objects.create_user(email="m@x.com", password="pw12345!")
        self.org = Organization.objects.create(name="Acme")
        self.org.add_member(self.owner, role=Role.OWNER)
        self.org.add_member(self.member, role=Role.MEMBER)
        self.project = Project.objects.create(organization=self.org, name="App")

    def _proposal_url(self):
        return reverse("technology:stack-proposal", args=[self.project.id])

    def _select_url(self):
        return reverse("technology:select-stack", args=[self.project.id])

    def test_proposal_404_before_architect_runs(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self._proposal_url()).status_code, 404)

    def test_proposal_returned_after_it_exists(self):
        from apps.project_context.models import ContextKind
        from apps.project_context.services import ProjectContext

        ProjectContext(self.project).set(
            ContextKind.STACK, "proposal", data={"roles": {"backend": {"recommended": "django"}}}
        )
        self.client.force_login(self.owner)
        resp = self.client.get(self._proposal_url())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["proposal"]["roles"]["backend"]["recommended"], "django")

    def test_owner_selects_stack(self):
        self.client.force_login(self.owner)
        resp = self.client.post(
            self._select_url(),
            {"backend": "django", "database": "postgresql"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.project.refresh_from_db()
        self.assertEqual(self.project.technology, {"backend": "django", "database": "postgresql"})

    def test_member_cannot_select(self):
        self.client.force_login(self.member)
        resp = self.client.post(
            self._select_url(),
            {"backend": "django"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_unknown_technology_rejected(self):
        self.client.force_login(self.owner)
        resp = self.client.post(
            self._select_url(),
            {"backend": "cobol_web"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)


class TechnologyAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="u@x.com", password="pw12345!")

    def test_technologies_requires_auth(self):
        self.assertEqual(self.client.get(reverse("technology:list")).status_code, 403)

    def test_technologies_lists_catalog(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("technology:list"))
        self.assertEqual(resp.status_code, 200)
        ids = {t["id"] for t in resp.json()}
        self.assertTrue({"python", "django", "go", "nextjs", "postgresql"} <= ids)

    def test_technologies_filter_by_category(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("technology:list") + "?category=database")
        cats = {t["category"] for t in resp.json()}
        self.assertEqual(cats, {"database"})

    def test_stacks_endpoint(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("technology:stacks"))
        ids = {s["id"] for s in resp.json()}
        self.assertEqual(ids, {"python-stdlib", "django", "fastapi", "node", "go"})
