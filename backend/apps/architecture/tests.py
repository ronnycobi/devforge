import json
from unittest import mock

from django.test import SimpleTestCase, TestCase

from apps.agents.runners import resolve_agent
from apps.ai_providers.base import CompletionResponse, Usage
from apps.architecture.agent import ArchitectAgent
from apps.architecture.parsing import parse_architecture
from apps.organizations.models import Organization
from apps.orchestrator.service import Orchestrator
from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.projects.models import Project

ARCH_JSON = json.dumps(
    {
        "components": [
            {
                "name": "API",
                "responsibility": "HTTP API for the app",
                "technology": "Django REST Framework",
                "depends_on": ["Database"],
            },
            {
                "name": "Database",
                "responsibility": "Persistent storage",
                "technology": "PostgreSQL",
                "depends_on": [],
            },
        ],
        "tech_decisions": [
            {
                "title": "Datastore",
                "choice": "PostgreSQL",
                "rationale": "Relational data with JSONB flexibility.",
            }
        ],
    }
)


def _fake_completion(text, model="claude-opus-5"):
    def _inner(request, provider=None):
        return CompletionResponse(
            text=text, model=model, provider="anthropic", usage=Usage(60, 120)
        )

    return _inner


class ParsingTests(SimpleTestCase):
    def test_parses_components_and_decisions(self):
        design = parse_architecture(ARCH_JSON)
        self.assertEqual(len(design["components"]), 2)
        self.assertEqual(len(design["tech_decisions"]), 1)
        self.assertEqual(design["components"][0]["depends_on"], ["Database"])

    def test_tolerates_bare_component_array(self):
        design = parse_architecture(json.dumps([{"name": "Worker"}]))
        self.assertEqual(len(design["components"]), 1)
        self.assertEqual(design["tech_decisions"], [])

    def test_garbage_returns_empty(self):
        design = parse_architecture("[stub:stub-1] design my app")
        self.assertEqual(design["components"], [])
        self.assertEqual(design["tech_decisions"], [])


class RunnerRegistrationTests(SimpleTestCase):
    def test_architect_runner_is_registered(self):
        self.assertIsInstance(resolve_agent("architect"), ArchitectAgent)

    def test_capabilities_are_scoped(self):
        caps = {c.value for c in ArchitectAgent.capabilities}
        self.assertIn("write_architecture", caps)
        self.assertIn("read_requirements", caps)
        self.assertNotIn("write_backend", caps)


class ArchitectAgentFlowTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(organization=self.org, name="App")
        # Seed a requirement so the architect has something to design from.
        ProjectContext(self.project).set(
            ContextKind.REQUIREMENT, "login", title="Login", content="Email login"
        )

    def _run(self):
        orch = Orchestrator()
        task = orch.create_task(project=self.project, agent_key="architect", input={})
        orch.run_task(task)
        task.refresh_from_db()
        return task

    def test_persists_components_and_decisions(self):
        with mock.patch(
            "apps.model_router.router.gateway_complete",
            side_effect=_fake_completion(ARCH_JSON),
        ):
            task = self._run()

        self.assertEqual(task.status, "completed")
        self.assertEqual(task.output["components_written"], 2)
        self.assertEqual(task.output["decisions_written"], 1)
        self.assertEqual(task.model, "claude-opus-5")

        ctx = ProjectContext(self.project)
        self.assertEqual(ctx.by_kind(ContextKind.ARCHITECTURE).count(), 2)
        self.assertEqual(ctx.by_kind(ContextKind.TECH_DECISION).count(), 1)
        api = ctx.get(ContextKind.ARCHITECTURE, "api")
        self.assertEqual(api.data["technology"], "Django REST Framework")

    def test_rerun_upserts_rather_than_duplicating(self):
        with mock.patch(
            "apps.model_router.router.gateway_complete",
            side_effect=_fake_completion(ARCH_JSON),
        ):
            self._run()
            self._run()  # same design again
        self.assertEqual(
            ProjectContext(self.project).by_kind(ContextKind.ARCHITECTURE).count(), 2
        )

    def test_offline_stub_completes_with_zero(self):
        task = self._run()  # no patch -> stub returns non-JSON
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.output["components_written"], 0)

    def test_fails_without_requirements_or_brief(self):
        bare = Project.objects.create(organization=self.org, name="Empty")
        orch = Orchestrator()
        task = orch.create_task(project=bare, agent_key="architect", input={})
        orch.run_task(task)
        task.refresh_from_db()
        self.assertEqual(task.status, "failed")
        self.assertIn("No requirements found", task.error)
