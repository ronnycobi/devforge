import json
import tempfile
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from apps.agents.runners import resolve_agent
from apps.ai_providers.base import CompletionResponse, Usage
from apps.backend.agent import BackendAgent
from apps.backend.parsing import parse_backend
from apps.organizations.models import Organization
from apps.orchestrator.service import Orchestrator
from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.projects.models import Project
from apps.repositories.service import repo_for_project

# A response with both API design and real (compiling) Python files.
GOOD_JSON = json.dumps(
    {
        "endpoints": [
            {"method": "post", "path": "/api/v1/jobs/", "purpose": "Create job", "module": "jobs"},
            {"method": "GET", "path": "/api/v1/jobs/", "purpose": "List jobs", "module": "jobs"},
        ],
        "files": [
            {
                "path": "backend/apps/jobs/models.py",
                "content": "class Job:\n    def __init__(self, title):\n        self.title = title\n",
            },
            {
                "path": "backend/apps/jobs/views.py",
                "content": "def list_jobs():\n    return []\n",
            },
        ],
    }
)

# Files that do NOT compile.
BROKEN_JSON = json.dumps(
    {
        "endpoints": [],
        "files": [{"path": "backend/bad.py", "content": "def broken(:\n  pass\n"}],
    }
)


def _fake(text, model="claude-opus-5"):
    def _inner(request, provider=None):
        return CompletionResponse(text=text, model=model, provider="anthropic", usage=Usage(80, 200))

    return _inner


class ParsingTests(SimpleTestCase):
    def test_endpoints_still_parse(self):
        self.assertEqual(len(parse_backend(GOOD_JSON)["endpoints"]), 2)


class RegistrationTests(SimpleTestCase):
    def test_registered(self):
        self.assertIsInstance(resolve_agent("backend"), BackendAgent)


class BackendCodegenFlowTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(organization=self.org, name="App")
        ProjectContext(self.project).set(
            ContextKind.ARCHITECTURE, "api", title="API", content="HTTP API"
        )

    def _run(self, response_text):
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                with mock.patch(
                    "apps.model_router.router.gateway_complete",
                    side_effect=_fake(response_text),
                ):
                    orch = Orchestrator()
                    task = orch.create_task(
                        project=self.project, agent_key="backend", input={}
                    )
                    orch.run_task(task)
                    task.refresh_from_db()
                    # Capture repo state before the temp dir is cleaned up.
                    files = repo_for_project(self.project).list_files()
        return task, files

    def test_generates_commits_and_verifies_code(self):
        task, files = self._run(GOOD_JSON)
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.output["files_generated"], 2)
        self.assertEqual(task.output["endpoints_written"], 2)
        self.assertTrue(task.output["verified"])  # compiled
        self.assertTrue(task.output["commit"])  # a commit sha
        self.assertIn("backend/apps/jobs/models.py", files)
        # API design persisted too.
        self.assertEqual(ProjectContext(self.project).by_kind(ContextKind.API).count(), 2)

    def test_reports_compile_failure_honestly(self):
        task, files = self._run(BROKEN_JSON)
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.output["files_generated"], 1)
        self.assertFalse(task.output["verified"])  # did NOT compile
        self.assertIn("backend/bad.py", files)  # still written for inspection
        self.assertIn("FAILED", task.messages[-1])

    def test_offline_stub_generates_nothing(self):
        orch = Orchestrator()
        task = orch.create_task(project=self.project, agent_key="backend", input={})
        orch.run_task(task)  # stub, no repo writes
        task.refresh_from_db()
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.output["files_generated"], 0)

    def test_fails_without_architecture(self):
        bare = Project.objects.create(organization=self.org, name="Empty")
        orch = Orchestrator()
        task = orch.create_task(project=bare, agent_key="backend", input={})
        orch.run_task(task)
        task.refresh_from_db()
        self.assertEqual(task.status, "failed")
