import json
import tempfile
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from apps.agents.runners import resolve_agent
from apps.ai_providers.base import CompletionResponse, Usage
from apps.devops.agent import DevOpsAgent
from apps.organizations.models import Organization
from apps.orchestrator.service import Orchestrator
from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.projects.models import Project
from apps.repositories.service import repo_for_project

INFRA_JSON = json.dumps(
    {
        "files": [
            {"path": "Dockerfile", "content": "FROM python:3.12-slim\nCMD [\"python\"]\n"},
            {
                "path": "docker-compose.yml",
                "content": "services:\n  web:\n    build: .\n  db:\n    image: postgres:16\n",
            },
        ]
    }
)


def _fake(text, model="claude-sonnet-5"):
    def _inner(request, provider=None):
        return CompletionResponse(text=text, model=model, provider="anthropic", usage=Usage(40, 90))

    return _inner


class RegistrationTests(SimpleTestCase):
    def test_registered(self):
        self.assertIsInstance(resolve_agent("devops"), DevOpsAgent)


class DevOpsFlowTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(
            organization=self.org,
            name="App",
            technology={"backend": "django", "database": "postgresql"},
        )
        ProjectContext(self.project).set(
            ContextKind.ARCHITECTURE, "api", title="API", content="Django backend"
        )

    def _run(self):
        orch = Orchestrator()
        task = orch.create_task(project=self.project, agent_key="devops", input={})
        orch.run_task(task)
        task.refresh_from_db()
        return task

    def test_generates_infra_files_for_stack(self):
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                with mock.patch(
                    "apps.model_router.router.gateway_complete", side_effect=_fake(INFRA_JSON)
                ):
                    task = self._run()
                files = repo_for_project(self.project).list_files()
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.output["files_generated"], 2)
        self.assertIn("backend: Django", task.output["stack"])
        self.assertIn("Dockerfile", files)
        self.assertIn("docker-compose.yml", files)
        # Recorded in context too.
        self.assertTrue(
            ProjectContext(self.project).by_kind(ContextKind.DEPLOYMENT).exists()
        )

    def test_offline_zero(self):
        self.assertEqual(self._run().output["files_generated"], 0)

    def test_fails_without_architecture(self):
        bare = Project.objects.create(organization=self.org, name="Empty")
        orch = Orchestrator()
        task = orch.create_task(project=bare, agent_key="devops", input={})
        orch.run_task(task)
        task.refresh_from_db()
        self.assertEqual(task.status, "failed")
