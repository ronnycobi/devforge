import json
import tempfile
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from apps.codegen.service import materialize

from apps.agents.runners import resolve_agent
from apps.ai_providers.base import CompletionResponse, Usage
from apps.organizations.models import Organization
from apps.orchestrator.service import Orchestrator
from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.projects.models import Project
from apps.testing.agent import TestingAgent
from apps.testing.parsing import parse_tests

TESTS_JSON = json.dumps(
    {
        "test_cases": [
            {
                "title": "Login with valid credentials",
                "kind": "e2e",
                "target": "POST /api/v1/auth/login",
                "steps": ["Submit valid email+password"],
                "expected": "200 and a session",
            },
            {"title": "Reject bad password", "kind": "weird", "expected": "401"},
        ]
    }
)


def _fake(text, model="claude-sonnet-5"):
    def _inner(request, provider=None):
        return CompletionResponse(text=text, model=model, provider="anthropic", usage=Usage(45, 95))

    return _inner


class ParsingTests(SimpleTestCase):
    def test_parses_and_defaults_kind(self):
        cases = parse_tests(TESTS_JSON)["test_cases"]
        self.assertEqual(len(cases), 2)
        self.assertEqual(cases[0]["kind"], "e2e")
        self.assertEqual(cases[1]["kind"], "integration")  # invalid -> default

    def test_garbage_empty(self):
        self.assertEqual(parse_tests("[stub] tests")["test_cases"], [])


class RegistrationTests(SimpleTestCase):
    def test_registered(self):
        self.assertIsInstance(resolve_agent("testing"), TestingAgent)

    def test_capabilities(self):
        caps = {c.value for c in TestingAgent.capabilities}
        self.assertIn("write_tests", caps)
        self.assertIn("run_tests", caps)
        self.assertNotIn("write_backend", caps)


class TestingFlowTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(organization=self.org, name="App")
        ProjectContext(self.project).set(
            ContextKind.REQUIREMENT, "login", title="Login", content="Email login"
        )

    def _run(self):
        orch = Orchestrator()
        task = orch.create_task(project=self.project, agent_key="testing", input={})
        orch.run_task(task)
        task.refresh_from_db()
        return task

    def test_persists_tests(self):
        with mock.patch("apps.model_router.router.gateway_complete", side_effect=_fake(TESTS_JSON)):
            task = self._run()
        self.assertEqual(task.output["tests_written"], 2)
        self.assertEqual(ProjectContext(self.project).by_kind(ContextKind.TESTING).count(), 2)

    def test_offline_zero(self):
        out = self._run().output
        self.assertEqual(out["tests_written"], 0)
        # No repo yet -> nothing to run, reported honestly.
        self.assertIsNone(out["test_run"]["passed"])

    def test_runs_passing_repo_tests_for_real(self):
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                materialize(
                    self.project,
                    [
                        {"path": "calc.py", "content": "def add(a, b):\n    return a + b\n"},
                        {
                            "path": "test_calc.py",
                            "content": (
                                "import unittest\nfrom calc import add\n\n"
                                "class T(unittest.TestCase):\n"
                                "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n"
                            ),
                        },
                    ],
                    message="seed",
                )
                task = self._run()
        run = task.output["test_run"]
        self.assertTrue(run["passed"])
        self.assertEqual(run["ran"], 1)
        self.assertEqual(run["failures"], 0)

    def test_reports_failing_repo_tests_for_real(self):
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                materialize(
                    self.project,
                    [
                        {"path": "calc.py", "content": "def add(a, b):\n    return a + b\n"},
                        {
                            "path": "test_calc.py",
                            "content": (
                                "import unittest\nfrom calc import add\n\n"
                                "class T(unittest.TestCase):\n"
                                "    def test_bad(self):\n        self.assertEqual(add(1, 1), 3)\n"
                            ),
                        },
                    ],
                    message="seed",
                )
                task = self._run()
        run = task.output["test_run"]
        self.assertFalse(run["passed"])
        self.assertEqual(run["failures"], 1)
        self.assertIn("FAILED", task.messages[-1])

    def test_fails_without_requirements(self):
        bare = Project.objects.create(organization=self.org, name="Empty")
        orch = Orchestrator()
        task = orch.create_task(project=bare, agent_key="testing", input={})
        orch.run_task(task)
        task.refresh_from_db()
        self.assertEqual(task.status, "failed")
