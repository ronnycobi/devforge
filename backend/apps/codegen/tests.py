import json
import tempfile

from django.test import SimpleTestCase, TestCase, override_settings

from apps.codegen.django_scaffold import normalize_app_label, scaffold_django_project
from apps.codegen.parsing import parse_files
from apps.codegen.service import materialize, verify_python
from apps.organizations.models import Organization
from apps.projects.models import Project
from apps.repositories.service import repo_for_project


class ParseFilesTests(SimpleTestCase):
    def test_parses_files_list(self):
        payload = json.dumps({"files": [{"path": "a.py", "content": "x = 1\n"}]})
        files = parse_files(payload)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["path"], "a.py")

    def test_rejects_unsafe_paths(self):
        payload = json.dumps(
            {"files": [
                {"path": "/etc/passwd", "content": "x"},
                {"path": "../escape.py", "content": "x"},
                {"path": "ok.py", "content": "x = 1\n"},
            ]}
        )
        files = parse_files(payload)
        self.assertEqual([f["path"] for f in files], ["ok.py"])

    def test_requires_string_content(self):
        payload = json.dumps({"files": [{"path": "a.py", "content": 123}]})
        self.assertEqual(parse_files(payload), [])

    def test_garbage_empty(self):
        self.assertEqual(parse_files("[stub] here is code"), [])


class VerifyPythonTests(SimpleTestCase):
    def test_valid_python_compiles(self):
        ok, log = verify_python([{"path": "m.py", "content": "def f():\n    return 1\n"}])
        self.assertTrue(ok)

    def test_invalid_python_fails(self):
        ok, log = verify_python([{"path": "m.py", "content": "def broken(:\n pass\n"}])
        self.assertFalse(ok)
        self.assertTrue(log)

    def test_no_python_is_ok(self):
        ok, log = verify_python([{"path": "app.dart", "content": "void main() {}"}])
        self.assertTrue(ok)
        self.assertIn("No Python", log)


class DjangoScaffoldTests(SimpleTestCase):
    def test_normalizes_app_label(self):
        self.assertEqual(normalize_app_label("My Shop!"), "my_shop_")
        self.assertEqual(normalize_app_label("123abc")[:4], "app_")

    def test_scaffold_wraps_app_files(self):
        files = scaffold_django_project("shop", {"models.py": "x = 1\n"})
        self.assertIn("manage.py", files)
        self.assertIn("settings.py", files)
        self.assertIn("devforge.json", files)
        self.assertIn("shop/models.py", files)
        self.assertIn('"shop"', files["settings.py"])  # app in INSTALLED_APPS
        self.assertIn("manage.py", files["devforge.json"])  # test command


class MaterializeTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(organization=self.org, name="App")

    def test_writes_and_commits_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                repo, sha = materialize(
                    self.project,
                    [{"path": "src/app.py", "content": "print('hi')\n"}],
                    message="gen",
                )
                self.assertTrue(sha)
                self.assertIn("src/app.py", repo.list_files())
                # idempotent: same content -> nothing to commit
                _, sha2 = materialize(
                    self.project,
                    [{"path": "src/app.py", "content": "print('hi')\n"}],
                    message="gen again",
                )
                self.assertIsNone(sha2)
