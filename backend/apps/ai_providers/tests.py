from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.agents.base import AgentContext, AgentResult, BaseAgent
from apps.ai_providers.anthropic_provider import AnthropicProvider
from apps.ai_providers.base import (
    CompletionRequest,
    Message,
    ProviderUnavailable,
)
from apps.ai_providers.registry import complete, get_provider, registry
from apps.ai_providers.stub import StubProvider
from apps.organizations.models import Organization
from apps.orchestrator.service import Orchestrator
from apps.projects.models import Project

User = get_user_model()


class StubProviderTests(SimpleTestCase):
    def test_is_deterministic_and_available(self):
        provider = StubProvider()
        self.assertTrue(provider.is_available())
        req = CompletionRequest(messages=[Message("user", "Hello there")])
        a = provider.complete(req)
        b = provider.complete(req)
        self.assertEqual(a.text, b.text)
        self.assertIn("Hello there", a.text)
        self.assertEqual(a.provider, "stub")
        self.assertGreater(a.usage.total_tokens, 0)


class AnthropicProviderTests(SimpleTestCase):
    @mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False)
    def test_unavailable_without_key(self):
        provider = AnthropicProvider()
        self.assertFalse(provider.is_available())

    @mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False)
    def test_complete_raises_when_unavailable(self):
        provider = AnthropicProvider()
        req = CompletionRequest(messages=[Message("user", "hi")])
        with self.assertRaises(ProviderUnavailable):
            provider.complete(req)

    def test_default_model_is_current(self):
        # Guards against a stale default sneaking in.
        self.assertEqual(AnthropicProvider().default_model(), "claude-opus-5")


class RegistryAndGatewayTests(SimpleTestCase):
    def test_registry_holds_stub_and_anthropic(self):
        self.assertIn("stub", registry)
        self.assertIn("anthropic", registry)

    def test_get_unknown_provider_raises(self):
        with self.assertRaises(ValueError):
            get_provider("ghost")

    def test_gateway_uses_default_provider_and_fills_model(self):
        # Default provider is the stub (settings AI_DEFAULT_PROVIDER).
        req = CompletionRequest(messages=[Message("user", "ping")])
        resp = complete(req)
        self.assertEqual(resp.provider, "stub")
        self.assertEqual(resp.model, "stub-1")  # default model filled in

    def test_gateway_accepts_explicit_provider_instance(self):
        req = CompletionRequest(messages=[Message("user", "ping")])
        resp = complete(req, provider=StubProvider())
        self.assertEqual(resp.provider, "stub")


class ProviderCatalogAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="dev@x.com", password="pw12345!")

    def test_requires_authentication(self):
        self.assertEqual(
            self.client.get(reverse("ai_providers:provider-list")).status_code, 403
        )

    def test_lists_providers_without_leaking_keys(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("ai_providers:provider-list"))
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        names = {p["name"] for p in body}
        self.assertEqual(names, {"stub", "anthropic"})
        stub = next(p for p in body if p["name"] == "stub")
        self.assertTrue(stub["available"])
        self.assertTrue(stub["is_default"])
        # No credential material anywhere in the payload.
        self.assertNotIn("key", resp.content.decode().lower())


class ProviderThroughOrchestratorTests(TestCase):
    """End-to-end: orchestrator -> agent -> provider, fully offline via stub."""

    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(organization=self.org, name="App")

    def test_agent_completes_task_using_the_provider(self):
        class _LLMAgent(BaseAgent):
            key = "backend"  # a real catalog key

            def execute(self, context):
                resp = complete(
                    CompletionRequest(
                        messages=[Message("user", context.input.get("prompt", ""))]
                    )
                )
                return AgentResult.completed(
                    self.key,
                    output={"text": resp.text, "model": resp.model},
                )

        orch = Orchestrator(resolver=lambda key: _LLMAgent())
        task = orch.create_task(
            project=self.project,
            agent_key="backend",
            input={"prompt": "Design a health endpoint"},
        )
        orch.run_task(task)
        task.refresh_from_db()

        self.assertEqual(task.status, "completed")
        self.assertIn("Design a health endpoint", task.output["text"])
        self.assertEqual(task.output["model"], "stub-1")
