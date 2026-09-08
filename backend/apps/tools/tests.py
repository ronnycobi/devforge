"""Tests for the Tool Registry, Toolbelt permission enforcement, and built-in tools."""
import tempfile

from django.test import TestCase, override_settings

from apps.agents.capabilities import Capability as C
from apps.organizations.models import Organization
from apps.projects.models import Project
from apps.tools.base import ToolNotFound, ToolPermissionDenied
from apps.tools.registry import Toolbelt, registry


class RegistryTests(TestCase):
    def test_builtin_tools_registered(self):
        names = {t.name for t in registry.all()}
        self.assertLessEqual(
            {"repo.read", "repo.write", "code.search", "tests.run", "sandbox.exec"}, names
        )

    def test_each_tool_declares_required_capabilities(self):
        for t in registry.all():
            self.assertTrue(t.required, f"{t.name} declares no required capabilities")


class PermissionTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(organization=self.org, name="App")

    def test_belt_lists_only_permitted_tools(self):
        # A read-only capability set: repo.read + code.search, but NOT repo.write.
        belt = Toolbelt(self.project, {C.USE_REPOSITORY})
        names = {t.name for t in belt.available()}
        self.assertIn("repo.read", names)
        self.assertIn("code.search", names)
        self.assertNotIn("repo.write", names)
        self.assertNotIn("sandbox.exec", names)

    def test_invoke_denied_without_capability(self):
        belt = Toolbelt(self.project, {C.USE_REPOSITORY})  # no WRITE_REPOSITORY
        with self.assertRaises(ToolPermissionDenied):
            belt.invoke("repo.write", "write_files", files={"a.py": "x=1\n"})

    def test_unknown_tool_raises(self):
        belt = Toolbelt(self.project, {C.USE_REPOSITORY})
        with self.assertRaises(ToolNotFound):
            belt.invoke("does.not.exist", "go")


class BuiltinToolTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(organization=self.org, name="App")

    def test_write_then_read_and_search(self):
        writer = Toolbelt(self.project, {C.WRITE_REPOSITORY})
        reader = Toolbelt(self.project, {C.USE_REPOSITORY})
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                w = writer.invoke("repo.write", "write_files",
                                  files={"svc.py": "def add(a, b):\n    return a + b\n"})
                self.assertTrue(w.ok)
                writer.invoke("repo.write", "commit", message="seed")

                r = reader.invoke("repo.read", "read_all")
                self.assertTrue(r.ok)
                self.assertIn("svc.py", r.data)

                s = reader.invoke("code.search", "search", pattern=r"def add")
                self.assertTrue(s.ok)
                self.assertEqual(s.data[0]["path"], "svc.py")

    def test_sandbox_verify_python(self):
        belt = Toolbelt(self.project, {C.USE_SANDBOX})
        res = belt.invoke("sandbox.exec", "verify_python",
                          files=[{"path": "ok.py", "content": "x = 1\n"}])
        self.assertTrue(res.ok)
        self.assertTrue(res.data["ok"])

    def test_tests_run_on_empty_repo_is_honest(self):
        belt = Toolbelt(self.project, {C.RUN_TESTS})
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                res = belt.invoke("tests.run", "run")
        self.assertTrue(res.ok)
        self.assertIsNone(res.data["passed"])  # nothing to run
