from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.agents.base import (
    AgentContext,
    AgentResult,
    AgentStatus,
    BaseAgent,
    CapabilityDenied,
)
from apps.agents.capabilities import SENSITIVE, Capability
from apps.agents.definitions import registry
from apps.agents.registry import AgentDefinition, AgentRegistry

User = get_user_model()


# --- Test fixture agents (explicitly not part of the shipped catalog) --------


class _RunsTestsAgent(BaseAgent):
    """Fixture: an agent that may run tests and nothing else."""

    key = "fixture_runner"
    name = "Fixture Runner"
    capabilities = frozenset({Capability.RUN_TESTS})

    def execute(self, context):
        self.require(Capability.RUN_TESTS)  # granted
        return AgentResult.completed(self.key, output={"echo": context.input})


class _OverreachingAgent(BaseAgent):
    """Fixture: tries to use a capability it was never granted."""

    key = "fixture_overreach"
    capabilities = frozenset({Capability.READ_BACKEND})

    def execute(self, context):
        self.require(Capability.WRITE_BACKEND)  # not granted -> denied
        return AgentResult.completed(self.key)


class _ExplodingAgent(BaseAgent):
    key = "fixture_boom"
    capabilities = frozenset()

    def execute(self, context):
        raise RuntimeError("kaboom")


class BaseAgentContractTests(SimpleTestCase):
    def test_run_returns_completed_result_on_success(self):
        result = _RunsTestsAgent().run(AgentContext(input={"a": 1}))
        self.assertTrue(result.ok)
        self.assertEqual(result.status, AgentStatus.COMPLETED)
        self.assertEqual(result.output, {"echo": {"a": 1}})

    def test_capability_denied_is_captured_as_failed_result(self):
        result = _OverreachingAgent().run(AgentContext())
        self.assertFalse(result.ok)
        self.assertEqual(result.status, AgentStatus.FAILED)
        self.assertIn("write_backend", result.error)

    def test_arbitrary_exception_becomes_failed_result_not_a_crash(self):
        result = _ExplodingAgent().run(AgentContext())
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "kaboom")

    def test_require_raises_for_missing_capability(self):
        with self.assertRaises(CapabilityDenied):
            _OverreachingAgent().require(Capability.MANAGE_BILLING)

    def test_unimplemented_agent_reports_blocker_not_fake_success(self):
        class _Bare(BaseAgent):
            key = "bare"

        result = _Bare().run(AgentContext())
        self.assertFalse(result.ok)
        self.assertIn("no executable behaviour yet", result.error)


class RegistryTests(SimpleTestCase):
    def test_catalog_has_the_ten_initial_agents(self):
        self.assertEqual(len(registry), 10)
        self.assertIn("lead", registry)
        self.assertIn("code_review", registry)

    def test_get_returns_definition(self):
        backend = registry.get("backend")
        self.assertEqual(backend.name, "Backend Agent")
        self.assertIn("write_backend", backend.capability_values)

    def test_duplicate_registration_rejected(self):
        reg = AgentRegistry()
        reg.register(AgentDefinition("x", "X", "", frozenset()))
        with self.assertRaises(ValueError):
            reg.register(AgentDefinition("x", "X again", "", frozenset()))


class LeastPrivilegeTests(SimpleTestCase):
    def test_no_default_agent_holds_a_sensitive_capability(self):
        for defn in registry.all():
            leaked = defn.capabilities & SENSITIVE
            self.assertFalse(
                leaked, f"{defn.key} unexpectedly holds {leaked}"
            )

    def test_frontend_cannot_touch_backend_or_billing(self):
        fe = registry.get("frontend")
        self.assertIn(Capability.WRITE_FRONTEND, fe.capabilities)
        self.assertNotIn(Capability.WRITE_BACKEND, fe.capabilities)
        self.assertNotIn(Capability.MANAGE_BILLING, fe.capabilities)

    def test_devops_deploys_dev_and_staging_but_not_production(self):
        ops = registry.get("devops")
        self.assertIn(Capability.DEPLOY_DEV, ops.capabilities)
        self.assertIn(Capability.DEPLOY_STAGING, ops.capabilities)
        self.assertNotIn(Capability.DEPLOY_PRODUCTION, ops.capabilities)

    def test_lead_orchestrates_but_writes_no_code(self):
        lead = registry.get("lead")
        self.assertIn(Capability.ORCHESTRATE, lead.capabilities)
        self.assertNotIn(Capability.WRITE_BACKEND, lead.capabilities)
        self.assertNotIn(Capability.WRITE_FRONTEND, lead.capabilities)


class AgentCatalogAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="dev@x.com", password="pw12345!")

    def test_list_requires_authentication(self):
        self.assertEqual(self.client.get(reverse("agents:list")).status_code, 403)

    def test_list_returns_full_catalog(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("agents:list"))
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body), 10)
        keys = {a["key"] for a in body}
        self.assertIn("architect", keys)
        lead = next(a for a in body if a["key"] == "lead")
        self.assertIn("orchestrate", lead["capabilities"])

    def test_detail_returns_one_agent(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("agents:detail", args=["testing"]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["name"], "Testing Agent")

    def test_unknown_agent_returns_404(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("agents:detail", args=["nope"]))
        self.assertEqual(resp.status_code, 404)
