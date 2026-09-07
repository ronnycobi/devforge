import json
from unittest import mock

from django.test import SimpleTestCase, TestCase

from apps.agents.runners import resolve_agent
from apps.ai_providers.base import CompletionResponse, Usage
from apps.frontend.agent import FrontendAgent
from apps.frontend.parsing import parse_frontend
from apps.organizations.models import Organization
from apps.orchestrator.service import Orchestrator
from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.projects.models import Project

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

    def test_fails_without_requirements(self):
        bare = Project.objects.create(organization=self.org, name="Empty")
        orch = Orchestrator()
        task = orch.create_task(project=bare, agent_key="frontend", input={})
        orch.run_task(task)
        task.refresh_from_db()
        self.assertEqual(task.status, "failed")
