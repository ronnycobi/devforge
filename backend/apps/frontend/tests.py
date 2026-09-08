import json
import tempfile
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from apps.agents.runners import resolve_agent
from apps.ai_providers.base import CompletionResponse, Usage
from apps.frontend.agent import FrontendAgent
from apps.frontend.parsing import parse_frontend
from apps.organizations.models import Organization
from apps.orchestrator.service import Orchestrator
from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.projects.models import Project
from apps.repositories.service import repo_for_project

SCREENS_JSON = json.dumps(
    {
        "screens": [
            {
                "name": "Login",
                "purpose": "Authenticate the user",
                "route": "/login",
                "components": ["EmailField", "PasswordField", "SubmitButton"],
                "data_needs": ["POST /api/v1/auth/login"],
            },
            {"name": "Dashboard", "purpose": "Overview", "route": "/"},
        ]
    }
)


def _fake(text, model="claude-sonnet-5"):
    def _inner(request, provider=None):
        return CompletionResponse(text=text, model=model, provider="anthropic", usage=Usage(40, 90))

    return _inner


def _sequence(*texts, model="claude-sonnet-5"):
    calls = {"n": 0}

    def _inner(request, provider=None):
        i = min(calls["n"], len(texts) - 1)
        calls["n"] += 1
        return CompletionResponse(text=texts[i], model=model, provider="anthropic", usage=Usage(40, 90))

    return _inner


# A React response: screens + real source (App.jsx) + a framework-free logic
# module and a node:test test that imports only the logic.
def _react_payload(add_body="a + b"):
    return json.dumps({
        "screens": [{"name": "Home", "purpose": "landing", "route": "/"}],
        "files": [
            {"path": "src/App.jsx", "content": (
                "import React from 'react';\n"
                "import { total } from './logic/cart.js';\n"
                "export default function App() { return <div>{total([1,2])}</div>; }\n"
            )},
            {"path": "src/logic/cart.js", "content": f"export const total = (xs) => xs.reduce((a, b) => {add_body}, 0);\n"},
            {"path": "src/logic/cart.test.js", "content": (
                "import { test } from 'node:test';\n"
                "import assert from 'node:assert';\n"
                "import { total } from './cart.js';\n\n"
                "test('total sums', () => { assert.strictEqual(total([1, 2, 3]), 6); });\n"
            )},
        ],
    })


class ParsingTests(SimpleTestCase):
    def test_parses_screens(self):
        screens = parse_frontend(SCREENS_JSON)["screens"]
        self.assertEqual(len(screens), 2)
        self.assertEqual(screens[0]["components"][0], "EmailField")

    def test_garbage_empty(self):
        self.assertEqual(parse_frontend("[stub] hi")["screens"], [])


class RegistrationTests(SimpleTestCase):
    def test_registered(self):
        self.assertIsInstance(resolve_agent("frontend"), FrontendAgent)

    def test_cannot_touch_backend(self):
        caps = {c.value for c in FrontendAgent.capabilities}
        self.assertIn("write_frontend", caps)
        self.assertNotIn("write_backend", caps)


class FrontendFlowTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(organization=self.org, name="App")
        ProjectContext(self.project).set(
            ContextKind.REQUIREMENT, "login", title="Login", content="Email login"
        )

    def _run(self):
        orch = Orchestrator()
        task = orch.create_task(project=self.project, agent_key="frontend", input={})
        orch.run_task(task)
        task.refresh_from_db()
        return task

    def test_persists_screens(self):
        with mock.patch("apps.model_router.router.gateway_complete", side_effect=_fake(SCREENS_JSON)):
            task = self._run()
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.output["screens_written"], 2)
        self.assertEqual(ProjectContext(self.project).by_kind(ContextKind.SCREEN).count(), 2)

    def test_offline_zero(self):
        self.assertEqual(self._run().output["screens_written"], 0)

    def test_stack_aware_records_framework(self):
        self.project.technology = {"frontend": "nextjs"}
        self.project.save(update_fields=["technology"])
        with mock.patch("apps.model_router.router.gateway_complete", side_effect=_fake(SCREENS_JSON)):
            task = self._run()
        self.assertEqual(task.output["frontend_stack"], "nextjs")
        screen = ProjectContext(self.project).by_kind(ContextKind.SCREEN).first()
        self.assertEqual(screen.data["framework"], "nextjs")
        self.assertEqual(screen.data["platform"], "web")

    def _run_src(self, side_effect, task_input=None):
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                with mock.patch(
                    "apps.model_router.router.gateway_complete", side_effect=side_effect
                ):
                    orch = Orchestrator()
                    task = orch.create_task(
                        project=self.project, agent_key="frontend", input=task_input or {}
                    )
                    orch.run_task(task)
                    task.refresh_from_db()
                    repo = repo_for_project(self.project)
                    files = repo.list_files() if repo.is_initialized else []
        return task, files

    def test_generates_react_source_and_runs_logic_tests(self):
        task, files = self._run_src(_fake(_react_payload()))
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.output["screens_written"], 1)   # design still kept
        self.assertTrue(task.output["code_generated"])
        self.assertTrue(task.output["verified"])              # no python → compiles
        self.assertTrue(task.output["tests_passed"])          # node --test logic passed
        self.assertIn("src/App.jsx", files)
        self.assertIn("src/logic/cart.js", files)
        self.assertIn("package.json", files)                  # DevForge scaffolded
        self.assertIn("devforge.json", files)

    def test_repairs_failing_logic_tests(self):
        # First implementation's logic is buggy (its own node:test fails); the
        # repair round fixes it and the suite goes green.
        task, _ = self._run_src(_sequence(_react_payload("a - b"), _react_payload("a + b")))
        self.assertEqual(task.status, "completed")
        self.assertTrue(task.output["tests_passed"])
        self.assertEqual(task.output["repair_rounds"], 1)

    def test_unrunnable_framework_stays_design_only(self):
        # A known framework with no runnable stack yet → design recorded, no source
        # generated, honestly not faked.
        self.project.technology = {"frontend": "nextjs"}
        self.project.save(update_fields=["technology"])
        task, files = self._run_src(_fake(_react_payload()))
        self.assertEqual(task.output["frontend_stack"], "nextjs")
        self.assertFalse(task.output["code_generated"])
        self.assertEqual(task.output["screens_written"], 1)
        self.assertEqual(files, [])

    def test_fails_without_requirements(self):
        bare = Project.objects.create(organization=self.org, name="Empty")
        orch = Orchestrator()
        task = orch.create_task(project=bare, agent_key="frontend", input={})
        orch.run_task(task)
        task.refresh_from_db()
        self.assertEqual(task.status, "failed")
