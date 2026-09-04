import json
from unittest import mock

from django.test import SimpleTestCase, TestCase

from apps.agents.runners import resolve_agent
from apps.ai_providers.base import CompletionResponse, Usage
from apps.code_review.agent import CodeReviewAgent
from apps.code_review.parsing import parse_findings
from apps.organizations.models import Organization
from apps.orchestrator.service import Orchestrator
from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.projects.models import Project

FINDINGS_JSON = json.dumps(
    {
        "findings": [
            {
                "title": "No auth on task endpoints",
                "severity": "high",
                "area": "API",
                "recommendation": "Require authentication.",
            },
            {"title": "Missing index", "severity": "unknown", "area": "schema"},
        ]
    }
)


def _fake(text, model="claude-opus-5"):
    def _inner(request, provider=None):
        return CompletionResponse(text=text, model=model, provider="anthropic", usage=Usage(80, 100))

    return _inner


class ParsingTests(SimpleTestCase):
    def test_parses_and_defaults_severity(self):
        findings = parse_findings(FINDINGS_JSON)["findings"]
        self.assertEqual(len(findings), 2)
        self.assertEqual(findings[0]["severity"], "high")
        self.assertEqual(findings[1]["severity"], "medium")  # invalid -> default

    def test_empty_findings_array_is_valid(self):
        self.assertEqual(parse_findings('{"findings": []}')["findings"], [])

    def test_garbage_empty(self):
        self.assertEqual(parse_findings("[stub] lgtm")["findings"], [])


class RegistrationTests(SimpleTestCase):
    def test_registered(self):
        self.assertIsInstance(resolve_agent("code_review"), CodeReviewAgent)

    def test_review_only_capabilities(self):
        caps = {c.value for c in CodeReviewAgent.capabilities}
        self.assertIn("review_code", caps)
        self.assertNotIn("write_backend", caps)
        self.assertNotIn("write_architecture", caps)


class CodeReviewFlowTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(organization=self.org, name="App")
        ProjectContext(self.project).set(
            ContextKind.API, "post-tasks", title="POST /tasks", content="create task"
        )

    def _run(self):
        orch = Orchestrator()
        task = orch.create_task(project=self.project, agent_key="code_review", input={})
        orch.run_task(task)
        task.refresh_from_db()
        return task

    def test_records_findings(self):
        with mock.patch("apps.model_router.router.gateway_complete", side_effect=_fake(FINDINGS_JSON)):
            task = self._run()
        self.assertEqual(task.output["findings_written"], 2)
        self.assertEqual(ProjectContext(self.project).by_kind(ContextKind.REVIEW).count(), 2)

    def test_offline_zero(self):
        self.assertEqual(self._run().output["findings_written"], 0)

    def test_fails_with_nothing_to_review(self):
        bare = Project.objects.create(organization=self.org, name="Empty")
        orch = Orchestrator()
        task = orch.create_task(project=bare, agent_key="code_review", input={})
        orch.run_task(task)
        task.refresh_from_db()
        self.assertEqual(task.status, "failed")
        self.assertIn("Nothing to review", task.error)
