import json
from unittest import mock

from django.test import SimpleTestCase, TestCase

from apps.agents.runners import resolve_agent
from apps.ai_providers.base import CompletionResponse, Usage
from apps.backend.agent import BackendAgent
from apps.backend.parsing import parse_backend
from apps.organizations.models import Organization
from apps.orchestrator.service import Orchestrator
from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.projects.models import Project

API_JSON = json.dumps(
    {
        "endpoints": [
            {
                "method": "post",
                "path": "/api/v1/tasks/",
                "purpose": "Create a task",
                "module": "tasks",
                "auth": "required",
                "request": {"title": "string"},
                "response": {"id": "int"},
            },
            {
                "method": "GET",
                "path": "/api/v1/tasks/",
                "purpose": "List tasks",
                "module": "tasks",
                "auth": "required",
            },
        ]
    }
)


def _fake_completion(text, model="claude-opus-5"):
    def _inner(request, provider=None):
        return CompletionResponse(
            text=text, model=model, provider="anthropic", usage=Usage(70, 140)
        )

    return _inner


class ParsingTests(SimpleTestCase):
    def test_parses_and_normalizes_endpoints(self):
        endpoints = parse_backend(API_JSON)["endpoints"]
        self.assertEqual(len(endpoints), 2)
        self.assertEqual(endpoints[0]["method"], "POST")  # upper-cased
        self.assertEqual(endpoints[0]["request"], {"title": "string"})

    def test_skips_endpoints_missing_method_or_path(self):
        payload = json.dumps({"endpoints": [{"path": "/x"}, {"method": "GET", "path": "/y"}]})
        self.assertEqual(len(parse_backend(payload)["endpoints"]), 1)

    def test_garbage_returns_empty(self):
        self.assertEqual(parse_backend("[stub:stub-1] build api")["endpoints"], [])


class RunnerRegistrationTests(SimpleTestCase):
    def test_backend_runner_registered(self):
        self.assertIsInstance(resolve_agent("backend"), BackendAgent)

    def test_capabilities_scoped(self):
        caps = {c.value for c in BackendAgent.capabilities}
        self.assertIn("write_backend", caps)
        self.assertIn("read_architecture", caps)
        self.assertNotIn("write_frontend", caps)
        self.assertNotIn("manage_billing", caps)


class BackendAgentFlowTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(organization=self.org, name="App")
        ProjectContext(self.project).set(
            ContextKind.ARCHITECTURE, "api", title="API", content="HTTP API"
        )

    def _run(self):
        orch = Orchestrator()
        task = orch.create_task(project=self.project, agent_key="backend", input={})
        orch.run_task(task)
        task.refresh_from_db()
        return task

    def test_persists_endpoints_as_api_entries(self):
        with mock.patch(
            "apps.model_router.router.gateway_complete",
            side_effect=_fake_completion(API_JSON),
        ):
            task = self._run()
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.output["endpoints_written"], 2)
        self.assertEqual(task.model, "claude-opus-5")
        api = ProjectContext(self.project).by_kind(ContextKind.API)
        self.assertEqual(api.count(), 2)
        self.assertTrue(api.filter(title="POST /api/v1/tasks/").exists())

    def test_rerun_upserts(self):
        with mock.patch(
            "apps.model_router.router.gateway_complete",
            side_effect=_fake_completion(API_JSON),
        ):
            self._run()
            self._run()
        self.assertEqual(
            ProjectContext(self.project).by_kind(ContextKind.API).count(), 2
        )

    def test_offline_stub_zero(self):
        task = self._run()
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.output["endpoints_written"], 0)

    def test_fails_without_architecture_or_brief(self):
        bare = Project.objects.create(organization=self.org, name="Empty")
        orch = Orchestrator()
        task = orch.create_task(project=bare, agent_key="backend", input={})
        orch.run_task(task)
        task.refresh_from_db()
        self.assertEqual(task.status, "failed")
        self.assertIn("No architecture found", task.error)
