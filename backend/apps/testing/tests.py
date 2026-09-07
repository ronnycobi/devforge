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
        # Isolate the workspaces root so tests never touch (or inherit) the
        # real on-disk workspaces dir used by the running app.
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        override = override_settings(DEVFORGE_WORKSPACES_ROOT=self._tmp.name)
        override.enable()
        self.addCleanup(override.disable)
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

    def test_runs_django_orm_tests_against_a_real_test_db(self):
        from apps.codegen.django_scaffold import scaffold_django_project

        scaffold = scaffold_django_project(
            "shop",
            {
                "models.py": (
                    "from django.db import models\n\n"
                    "class Product(models.Model):\n"
                    "    name = models.CharField(max_length=50)\n"
                ),
                "tests.py": (
                    "from django.test import TestCase\nfrom shop.models import Product\n\n"
                    "class ProductTests(TestCase):\n"
                    "    def test_create_and_query(self):\n"
                    "        Product.objects.create(name='x')\n"
                    "        self.assertEqual(Product.objects.count(), 1)\n"
                ),
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                materialize(
                    self.project,
                    [{"path": p, "content": c} for p, c in scaffold.items()],
                    message="seed django app",
                )
                task = self._run()
        run = task.output["test_run"]
        self.assertTrue(run["passed"])  # real manage.py test against a real DB
        self.assertEqual(run["ran"], 1)
        self.assertEqual(run["failures"], 0)

    def test_runs_fastapi_api_tests_for_real(self):
        # A FastAPI project whose tests hit the app in-process via TestClient.
        materialize_files = [
            {
                "path": "main.py",
                "content": (
                    "from fastapi import FastAPI\n\n"
                    "app = FastAPI()\n\n"
                    "@app.get('/ping')\n"
                    "def ping():\n    return {'ok': True}\n"
                ),
            },
            {
                "path": "test_main.py",
                "content": (
                    "import unittest\nfrom fastapi.testclient import TestClient\n"
                    "from main import app\n\n"
                    "class ApiTests(unittest.TestCase):\n"
                    "    def test_ping(self):\n"
                    "        r = TestClient(app).get('/ping')\n"
                    "        self.assertEqual(r.status_code, 200)\n"
                    "        self.assertEqual(r.json(), {'ok': True})\n"
                ),
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                materialize(self.project, materialize_files, message="seed fastapi")
                task = self._run()
        run = task.output["test_run"]
        self.assertTrue(run["passed"])  # real in-process API call succeeded
        self.assertEqual(run["ran"], 1)

    def test_runs_node_builtin_http_tests_for_real(self):
        import shutil

        if not shutil.which("node"):
            self.skipTest("node not installed")
        from apps.codegen.node_scaffold import scaffold_node_project

        app_files = {
            "app.js": (
                "const http=require('node:http');\n"
                "function makeServer(){return http.createServer((req,res)=>res.end(JSON.stringify({ok:true})));}\n"
                "module.exports={makeServer};\n"
            ),
            "app.test.js": (
                "const {test}=require('node:test');const assert=require('node:assert');\n"
                "const {makeServer}=require('./app');\n"
                "test('responds ok', async ()=>{\n"
                "  const s=makeServer().listen(0);const p=s.address().port;\n"
                "  const r=await fetch(`http://127.0.0.1:${p}`);\n"
                "  assert.deepEqual(await r.json(), {ok:true});\n"
                "  s.close();\n"
                "});\n"
            ),
        }
        scaffold = scaffold_node_project("app", app_files)
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                materialize(
                    self.project,
                    [{"path": p, "content": c} for p, c in scaffold.items()],
                    message="seed node",
                )
                task = self._run()
        run = task.output["test_run"]
        self.assertTrue(run["passed"])  # real node --test HTTP call succeeded
        self.assertEqual(run["ran"], 1)

    def test_go_project_runs_or_skips_honestly(self):
        import shutil

        from apps.codegen.go_scaffold import scaffold_go_project

        scaffold = scaffold_go_project(
            "app",
            {
                "app.go": "package app\n\nfunc Add(a, b int) int { return a + b }\n",
                "app_test.go": (
                    "package app\n\nimport \"testing\"\n\n"
                    "func TestAdd(t *testing.T){ if Add(2,3)!=5 {t.Fatal(\"x\")} }\n"
                ),
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                materialize(
                    self.project,
                    [{"path": p, "content": c} for p, c in scaffold.items()],
                    message="seed go",
                )
                task = self._run()
        run = task.output["test_run"]
        if shutil.which("go"):
            self.assertTrue(run["passed"])  # real `go test` where go is installed
        else:
            # Honest skip, not a confusing failure, where go is absent.
            self.assertIsNone(run["passed"])
            self.assertIn("go", run["note"])

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
