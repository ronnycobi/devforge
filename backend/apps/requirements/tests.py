import json
from unittest import mock

from django.test import SimpleTestCase, TestCase

from apps.agents.runners import resolve_agent
from apps.ai_providers.base import CompletionResponse, Usage
from apps.organizations.models import Organization
from apps.orchestrator.service import Orchestrator
from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.projects.models import Project
from apps.requirements.agent import RequirementsAgent
from apps.requirements.parsing import parse_requirements

REQ_JSON = json.dumps(
    [
        {
            "title": "Email login",
            "description": "Users log in with email and password.",
            "acceptance_criteria": ["Valid creds succeed", "Invalid creds rejected"],
        },
        {
            "title": "Password reset",
            "description": "Users reset via an emailed link.",
            "acceptance_criteria": ["Reset link expires in 1 hour"],
        },
    ]
)


def _fake_completion(text, model="claude-opus-5"):
    def _inner(request, provider=None):
        return CompletionResponse(
            text=text,
            model=model,
            provider="anthropic",
            usage=Usage(input_tokens=50, output_tokens=80),
        )

    return _inner


class ParsingTests(SimpleTestCase):
    def test_parses_plain_json_array(self):
        reqs = parse_requirements(REQ_JSON)
        self.assertEqual(len(reqs), 2)
        self.assertEqual(reqs[0]["title"], "Email login")
        self.assertEqual(len(reqs[0]["acceptance_criteria"]), 2)

    def test_parses_fenced_and_prose_wrapped_json(self):
        fenced = "```json\n" + REQ_JSON + "\n```"
        self.assertEqual(len(parse_requirements(fenced)), 2)
        prose = "Here are the requirements:\n" + REQ_JSON + "\nHope that helps!"
        self.assertEqual(len(parse_requirements(prose)), 2)

    def test_parses_object_with_requirements_key(self):
        payload = json.dumps({"requirements": json.loads(REQ_JSON)})
        self.assertEqual(len(parse_requirements(payload)), 2)

    def test_garbage_returns_empty_not_crash(self):
        self.assertEqual(parse_requirements("[stub:stub-1] build me an app"), [])
        self.assertEqual(parse_requirements(""), [])
        self.assertEqual(parse_requirements("not json at all"), [])

    def test_skips_items_without_a_title(self):
        payload = json.dumps([{"description": "no title"}, {"title": "Has title"}])
        reqs = parse_requirements(payload)
        self.assertEqual(len(reqs), 1)


class RunnerRegistrationTests(SimpleTestCase):
    def test_requirements_runner_is_registered(self):
        agent = resolve_agent("requirements")
        self.assertIsInstance(agent, RequirementsAgent)

    def test_agent_only_holds_requirements_capabilities(self):
        caps = {c.value for c in RequirementsAgent.capabilities}
        self.assertIn("write_requirements", caps)
        self.assertNotIn("write_backend", caps)
        self.assertNotIn("manage_billing", caps)


class RequirementsAgentFlowTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(organization=self.org, name="App")

    def _run(self, brief):
        orch = Orchestrator()  # default resolver -> the registered RequirementsAgent
        task = orch.create_task(
            project=self.project,
            agent_key="requirements",
            input={"brief": brief},
        )
        orch.run_task(task)
        task.refresh_from_db()
        return task

    def test_extracts_and_persists_requirements(self):
        with mock.patch(
            "apps.model_router.router.gateway_complete",
            side_effect=_fake_completion(REQ_JSON),
        ):
            task = self._run("A SaaS for construction project management")

        self.assertEqual(task.status, "completed")
        self.assertEqual(task.output["requirements_created"], 2)
        self.assertEqual(task.model, "claude-opus-5")
        self.assertGreater(task.tokens, 0)

        reqs = ProjectContext(self.project).by_kind(ContextKind.REQUIREMENT)
        self.assertEqual(reqs.count(), 2)
        login = reqs.filter(title="Email login").first()
        self.assertIsNotNone(login)
        self.assertEqual(len(login.data["acceptance_criteria"]), 2)
        self.assertTrue(login.source.startswith("agent:requirements#task:"))

    def test_offline_stub_completes_honestly_with_zero(self):
        # No patch -> stub provider returns non-JSON; agent writes nothing.
        task = self._run("Anything at all")
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.output["requirements_created"], 0)
        self.assertEqual(
            ProjectContext(self.project).by_kind(ContextKind.REQUIREMENT).count(), 0
        )
        self.assertIn("no parseable requirements", task.messages[0])

    def test_missing_brief_fails(self):
        orch = Orchestrator()
        task = orch.create_task(
            project=self.project, agent_key="requirements", input={}
        )
        orch.run_task(task)
        task.refresh_from_db()
        self.assertEqual(task.status, "failed")
        self.assertIn("No 'brief'", task.error)
