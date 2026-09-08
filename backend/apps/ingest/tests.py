"""Tests for importing and analyzing an existing codebase."""
import io
import tempfile
import zipfile
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.ingest import analyzer
from apps.ingest.detect import detect_databases, detect_dependencies, detect_stack
from apps.organizations.models import Membership, Organization, Role
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

    def test_detect_databases_django_postgres_and_redis(self):
        files = {
            "config/settings.py": "DATABASES = {'default': {'ENGINE': 'django.db.backends.postgresql'}}\n",
            "requirements.txt": "Django\npsycopg2-binary\nredis\n",
            "docker-compose.yml": "services:\n  cache:\n    image: redis:7\n",
        }
        dbs = detect_databases(files)
        self.assertIn("postgresql", dbs)
        self.assertIn("redis", dbs)

    def test_detect_databases_node_mongo(self):
        pkg = '{"dependencies": {"mongoose": "8", "express": "4"}}'
        self.assertEqual(detect_databases({"package.json": pkg}), ["mongodb"])

    def test_detect_databases_none(self):
        self.assertEqual(detect_databases({"main.py": "print(1)\n"}), [])


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

    def test_import_detects_database_into_twin(self):
        project = Project.objects.create(
            organization=self.org, name="Legacy", mode=Mode.BUILD, created_by=self.user
        )
        files = {
            "manage.py": "import django\n",
            "config/settings.py": "DATABASES={'default':{'ENGINE':'django.db.backends.postgresql'}}\n",
            "requirements.txt": "Django\npsycopg2\nredis\n",
            "billing/models.py": "x = 1\n",
        }
        summary = analyzer.import_codebase(project, files, created_by=self.user)

        project.refresh_from_db()
        self.assertEqual(project.technology.get("database"), "postgresql")  # system of record
        self.assertIn("postgresql", summary["databases"])
        self.assertIn("redis", summary["databases"])          # cache detected too
        self.assertEqual(summary["primary_database"], "postgresql")

        decision = ContextEntry.objects.get(project=project, key="detected-databases")
        self.assertEqual(decision.kind, ContextKind.TECH_DECISION)
        self.assertEqual(decision.data["primary"], "postgresql")
        self.assertFalse(decision.data["capabilities"]["redis"]["foreign_keys"])


class GitImportViewTests(TestCase):
    """The Analyze-Software page importing from a Git provider (fetch mocked)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        override = override_settings(DEVFORGE_WORKSPACES_ROOT=self._tmp.name)
        override.enable()
        self.addCleanup(override.disable)
        self.user = User.objects.create_user(email="owner@acme.com", password="x")
        self.org = Organization.objects.create(name="Acme", created_by=self.user)
        Membership.objects.create(organization=self.org, user=self.user, role=Role.OWNER)
        self.client.force_login(self.user)

    def _archive(self):
        return _zip({
            "manage.py": "import django\n",
            "requirements.txt": "Django==6.0\n",
            "billing/models.py": "class Invoice: pass\n",
        }, root="acme-billing-deadbeef")

    def test_git_import_creates_project_and_twin(self):
        with mock.patch("apps.ingest.connect.fetch_repo_archive", return_value=self._archive()) as fetch:
            r = self.client.post(reverse("dashboard:import"), {
                "source": "git", "provider": "github", "name": "Billing",
                "organization": self.org.id, "repo": "acme/billing", "ref": "main",
            })
        self.assertEqual(r.status_code, 302)
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.args[0], "github")
        project = Project.objects.get(name="Billing")
        self.assertEqual(project.mode, "import")
        self.assertEqual(project.technology.get("backend"), "django")

    def test_git_connect_error_surfaces_no_project(self):
        from apps.ingest.connect import ConnectError
        with mock.patch("apps.ingest.connect.fetch_repo_archive",
                        side_effect=ConnectError("Repository or branch not found.")):
            r = self.client.post(reverse("dashboard:import"), {
                "source": "git", "provider": "github", "name": "Ghost",
                "organization": self.org.id, "repo": "acme/nope",
            }, follow=True)
        self.assertFalse(Project.objects.filter(name="Ghost").exists())
        self.assertContains(r, "not found")
