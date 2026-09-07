import json
from unittest import mock

from django.test import SimpleTestCase, TestCase

from apps.agents.runners import resolve_agent
from apps.ai_providers.base import CompletionResponse, Usage
from apps.mobile.agent import MobileAgent
from apps.organizations.models import Organization
from apps.orchestrator.service import Orchestrator
from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.projects.models import Project

SCREENS_JSON = json.dumps(
    {"screens": [{"name": "Home", "purpose": "Landing", "route": "/", "components": ["List"]}]}
)


def _fake(text, model="claude-sonnet-5"):
    def _inner(request, provider=None):
        return CompletionResponse(text=text, model=model, provider="anthropic", usage=Usage(30, 70))

    return _inner


class RegistrationTests(SimpleTestCase):
    def test_registered(self):
        self.assertIsInstance(resolve_agent("mobile"), MobileAgent)


class MobileFlowTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(
            organization=self.org, name="App", technology={"mobile": "flutter"}
        )
        ProjectContext(self.project).set(
            ContextKind.REQUIREMENT, "r", title="R", content="mobile users"
        )

    def _run(self):
        orch = Orchestrator()
        task = orch.create_task(project=self.project, agent_key="mobile", input={})
        orch.run_task(task)
        task.refresh_from_db()
        return task

    def test_designs_mobile_screens_for_chosen_framework(self):
        with mock.patch("apps.model_router.router.gateway_complete", side_effect=_fake(SCREENS_JSON)):
            task = self._run()
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.output["screens_written"], 1)
        self.assertEqual(task.output["mobile_stack"], "flutter")
        screen = ProjectContext(self.project).by_kind(ContextKind.SCREEN).first()
        self.assertEqual(screen.data["platform"], "mobile")
        self.assertEqual(screen.data["framework"], "flutter")

    def test_offline_zero(self):
        self.assertEqual(self._run().output["screens_written"], 0)

    def test_fails_without_requirements(self):
        bare = Project.objects.create(organization=self.org, name="Empty")
        orch = Orchestrator()
        task = orch.create_task(project=bare, agent_key="mobile", input={})
        orch.run_task(task)
        task.refresh_from_db()
        self.assertEqual(task.status, "failed")
