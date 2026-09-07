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


class StackTests(SimpleTestCase):
    def test_runnable_stacks_registered(self):
        ids = {s.id for s in backend_stacks()}
        self.assertEqual(ids, {"python-stdlib", "django"})

    def test_python_stacks_are_runnable(self):
        self.assertTrue(get_stack("django").is_runnable())
        self.assertTrue(get_stack("python-stdlib").is_runnable())

    def test_django_scaffolds_stdlib_does_not(self):
        dj = get_stack("django").build_project("shop", [{"path": "models.py", "content": "x=1\n"}])
        paths = {f["path"] for f in dj}
        self.assertIn("manage.py", paths)
        self.assertIn("shop/models.py", paths)

        flat = get_stack("python-stdlib").build_project(None, [{"path": "app.py", "content": "x=1\n"}])
        self.assertEqual([f["path"] for f in flat], ["app.py"])

    def test_unknown_stack_returns_none(self):
        self.assertIsNone(get_stack("cobol"))


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
        self.assertEqual(ids, {"python-stdlib", "django"})
        self.assertTrue(all(s["runnable"] for s in resp.json()))
