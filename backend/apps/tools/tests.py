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


class ConnectorTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(organization=self.org, name="App")

    def test_connectors_require_the_connector_capability(self):
        # A belt without USE_CONNECTORS can't see or invoke a connector.
        belt = Toolbelt(self.project, {C.USE_REPOSITORY})
        self.assertNotIn("connector.github", {t.name for t in belt.available()})
        with self.assertRaises(ToolPermissionDenied):
            belt.invoke("connector.github", "repo.info")
        # With the capability it's available.
        belt2 = Toolbelt(self.project, {C.USE_CONNECTORS})
        self.assertIn("connector.github", {t.name for t in belt2.available()})

    def test_unconfigured_connector_refuses_honestly(self):
        import os
        from unittest import mock
        belt = Toolbelt(self.project, {C.USE_CONNECTORS})
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GITHUB_TOKEN", None)
            r = belt.invoke("connector.github", "repo.info")
        self.assertFalse(r.ok)
        self.assertIn("not configured", r.error.lower())

    def test_configured_connector_does_not_fake(self):
        import os
        from unittest import mock
        belt = Toolbelt(self.project, {C.USE_CONNECTORS})
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_secret"}, clear=False):
            r = belt.invoke("connector.github", "repo.info")
        # Credential present, but no live integration → still refuses, never fabricates.
        self.assertFalse(r.ok)
        self.assertIn("not enabled", r.error.lower())

    def test_status_and_describe_never_leak_the_secret(self):
        import os
        from unittest import mock
        from apps.tools.connectors import connector_status, GitHubConnector
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_supersecret"}, clear=False):
            status = {c["provider"]: c for c in connector_status()}
            self.assertTrue(status["GitHub"]["configured"])
            self.assertEqual(status["GitHub"]["credential_env"], "GITHUB_TOKEN")
            blob = str(connector_status()) + str(GitHubConnector().describe())
        self.assertNotIn("ghp_supersecret", blob)   # the value never appears anywhere
