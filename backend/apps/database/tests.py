import json
import tempfile
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from apps.repositories.service import repo_for_project

from apps.agents.runners import resolve_agent
from apps.ai_providers.base import CompletionResponse, Usage
from apps.database.agent import DatabaseAgent
from apps.database.parsing import parse_schema
from apps.organizations.models import Organization
from apps.orchestrator.service import Orchestrator
from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.projects.models import Project

SCHEMA_JSON = json.dumps(
    {
        "models": [
            {
                "name": "User",
                "description": "Account",
                "fields": [
                    {"name": "email", "type": "varchar", "nullable": False},
                    {"name": "created_at", "type": "timestamp"},
                ],
                "relations": ["has_many Task"],
            },
            {"name": "Task", "description": "Work item", "fields": [{"name": "title", "type": "text"}]},
        ]
    }
)


def _fake(text, model="claude-opus-5"):
    def _inner(request, provider=None):
        return CompletionResponse(text=text, model=model, provider="anthropic", usage=Usage(50, 110))

    return _inner


class ParsingTests(SimpleTestCase):
    def test_parses_models_and_fields(self):
        models = parse_schema(SCHEMA_JSON)["models"]
        self.assertEqual(len(models), 2)
        self.assertEqual(models[0]["fields"][0]["name"], "email")
        self.assertFalse(models[0]["fields"][0]["nullable"])

    def test_accepts_entities_key_and_string_fields(self):
        payload = json.dumps({"entities": [{"name": "X", "fields": ["a", "b"]}]})
        models = parse_schema(payload)["models"]
        self.assertEqual(len(models[0]["fields"]), 2)

    def test_garbage_empty(self):
        self.assertEqual(parse_schema("[stub] db")["models"], [])


class RegistrationTests(SimpleTestCase):
    def test_registered(self):
        self.assertIsInstance(resolve_agent("database"), DatabaseAgent)

    def test_no_prod_data_capability(self):
        caps = {c.value for c in DatabaseAgent.capabilities}
        self.assertIn("write_migrations", caps)
        self.assertNotIn("access_production_secrets", caps)


class DatabaseFlowTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(organization=self.org, name="App")
        ProjectContext(self.project).set(
            ContextKind.REQUIREMENT, "tasks", title="Tasks", content="CRUD tasks"
        )

    def _run(self):
        orch = Orchestrator()
        task = orch.create_task(project=self.project, agent_key="database", input={})
        orch.run_task(task)
        task.refresh_from_db()
        return task

    def test_persists_models(self):
        with mock.patch("apps.model_router.router.gateway_complete", side_effect=_fake(SCHEMA_JSON)):
            task = self._run()
        self.assertEqual(task.output["models_written"], 2)
        self.assertEqual(ProjectContext(self.project).by_kind(ContextKind.SCHEMA).count(), 2)

    def test_offline_zero(self):
        self.assertEqual(self._run().output["models_written"], 0)

    def test_generates_and_verifies_model_files(self):
        payload = json.dumps(
            {
                "models": [{"name": "Task", "fields": [{"name": "title", "type": "text"}]}],
                "files": [
                    {
                        "path": "backend/apps/core/models.py",
                        "content": "class Task:\n    title = ''\n",
                    }
                ],
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                with mock.patch(
                    "apps.model_router.router.gateway_complete",
                    side_effect=_fake(payload),
                ):
                    orch = Orchestrator()
                    task = orch.create_task(
                        project=self.project, agent_key="database", input={}
                    )
                    orch.run_task(task)
                    task.refresh_from_db()
                    files = repo_for_project(self.project).list_files()
        self.assertEqual(task.output["models_written"], 1)
        self.assertEqual(task.output["files_generated"], 1)
        self.assertTrue(task.output["verified"])
        self.assertIn("backend/apps/core/models.py", files)

    def test_fails_without_upstream(self):
        bare = Project.objects.create(organization=self.org, name="Empty")
        orch = Orchestrator()
        task = orch.create_task(project=bare, agent_key="database", input={})
        orch.run_task(task)
        task.refresh_from_db()
        self.assertEqual(task.status, "failed")
