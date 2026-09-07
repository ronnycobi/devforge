"""Tests for importing and analyzing an existing codebase."""
import io
import tempfile
import zipfile

from django.test import TestCase, override_settings

from apps.accounts.models import User
from apps.ingest import analyzer
from apps.ingest.detect import detect_dependencies, detect_stack
from apps.organizations.models import Organization
from apps.project_context.models import ContextEntry, ContextKind
from apps.projects.models import Mode, Project


def _zip(files: dict, root: str | None = None) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, content in files.items():
            name = f"{root}/{path}" if root else path
            if isinstance(content, bytes):
                zf.writestr(name, content)
            else:
                zf.writestr(name, content)
    buf.seek(0)
    return buf


class DetectTests(TestCase):
    def test_django_stack_from_manifest(self):
        files = {"manage.py": "", "requirements.txt": "Django==6.0\ndrf\n"}
        self.assertEqual(detect_stack(files)["backend"], "django")

    def test_react_frontend_and_express_backend(self):
        pkg = '{"dependencies": {"express": "4", "react": "18"}}'
        stack = detect_stack({"package.json": pkg})
        self.assertEqual(stack["backend"], "express")
        self.assertEqual(stack["frontend"], "react")

    def test_go_stack(self):
        self.assertEqual(detect_stack({"go.mod": "module x\n"})["backend"], "go")

    def test_dependencies_from_requirements(self):
        deps = detect_dependencies({"requirements.txt": "Django==6.0\n# note\nrequests>=2\n"})
        self.assertIn("Django", deps)
        self.assertIn("requests", deps)
        self.assertNotIn("# note", deps)


class ExtractZipTests(TestCase):
    def test_strips_single_top_folder(self):
        files = analyzer.extract_zip(_zip({"app/main.py": "print(1)\n"}, root="myproj"))
        self.assertIn("app/main.py", files)

    def test_rejects_bad_zip(self):
        with self.assertRaises(analyzer.IngestError):
            analyzer.extract_zip(io.BytesIO(b"not a zip"))

    def test_skips_traversal_and_junk(self):
        files = analyzer.extract_zip(_zip({
            "src/ok.py": "x = 1\n",
            "../evil.py": "danger\n",
            "node_modules/lib/index.js": "junk\n",
            "logo.png": b"\x89PNG\r\n",
        }))
        self.assertIn("src/ok.py", files)
        self.assertNotIn("../evil.py", files)
        self.assertFalse(any("node_modules" in p for p in files))
        self.assertNotIn("logo.png", files)

    def test_empty_archive_raises(self):
        with self.assertRaises(analyzer.IngestError):
            analyzer.extract_zip(_zip({"logo.png": b"\x89PNG"}))


class ImportCodebaseTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        override = override_settings(DEVFORGE_WORKSPACES_ROOT=self._tmp.name)
        override.enable()
        self.addCleanup(override.disable)
        self.user = User.objects.create_user(email="o@e.com", password="x")
        self.org = Organization.objects.create(name="Acme", created_by=self.user)

    def test_import_populates_twin_and_technology(self):
        project = Project.objects.create(
            organization=self.org, name="Legacy", mode=Mode.BUILD, created_by=self.user
        )
        files = {
            "manage.py": "import django\n",
            "requirements.txt": "Django==6.0\nrequests\n",
            "billing/models.py": "class Invoice: pass\n",
            "api/views.py": "def list(r): ...\n",
        }
        summary = analyzer.import_codebase(project, files, created_by=self.user)

        project.refresh_from_db()
        self.assertEqual(project.mode, "import")
        self.assertEqual(project.technology.get("backend"), "django")
        self.assertEqual(summary["files"], 4)

        kinds = ContextEntry.objects.filter(project=project)
        self.assertTrue(kinds.filter(kind=ContextKind.ARCHITECTURE, key="codebase-overview").exists())
        self.assertTrue(kinds.filter(kind=ContextKind.DEPENDENCY, key="dependencies").exists())
        # top-level dirs recorded as components
        self.assertIn("billing", summary["components"])
