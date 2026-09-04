from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.ai_providers.base import (
    CompletionResponse,
    Message,
    ProviderUnavailable,
    Usage,
)
from apps.model_router.router import (
    ModelRouter,
    NoModelAvailable,
    RoutingRequest,
    TaskComplexity,
)

User = get_user_model()

# Make the Anthropic provider "available" so real routing can be exercised
# without a live key. Applied per-test where real models must be candidates.
anthropic_up = mock.patch(
    "apps.ai_providers.anthropic_provider.AnthropicProvider.is_available",
    return_value=True,
)


class RoutingPolicyTests(SimpleTestCase):
    def setUp(self):
        self.router = ModelRouter()

    @anthropic_up
    def test_medium_picks_cheapest_sufficient(self, _):
        d = self.router.route(RoutingRequest(complexity=TaskComplexity.MEDIUM))
        self.assertEqual(d.model, "claude-sonnet-5")  # tier 2, cheaper than opus

    @anthropic_up
    def test_low_prefers_real_model_over_free_stub(self, _):
        d = self.router.route(RoutingRequest(complexity=TaskComplexity.LOW))
        self.assertEqual(d.model, "claude-haiku-4-5")  # not the $0 stub

    @anthropic_up
    def test_high_picks_top_tier(self, _):
        d = self.router.route(RoutingRequest(complexity=TaskComplexity.HIGH))
        self.assertEqual(d.model, "claude-opus-5")

    @anthropic_up
    def test_prefer_quality_upgrades_medium_to_opus(self, _):
        d = self.router.route(
            RoutingRequest(complexity=TaskComplexity.MEDIUM, prefer_quality=True)
        )
        self.assertEqual(d.model, "claude-opus-5")

    @anthropic_up
    def test_preferred_model_is_honoured(self, _):
        d = self.router.route(
            RoutingRequest(
                complexity=TaskComplexity.HIGH, preferred_model="claude-haiku-4-5"
            )
        )
        self.assertEqual(d.model, "claude-haiku-4-5")
        self.assertIn("Honoured", d.reason)

    @anthropic_up
    def test_budget_forces_cheaper_and_marks_degraded(self, _):
        # avg cost: haiku 3, sonnet 6, opus 15. Budget 4 rules out sonnet/opus.
        d = self.router.route(
            RoutingRequest(complexity=TaskComplexity.HIGH, max_cost_per_mtok=4.0)
        )
        self.assertEqual(d.model, "claude-haiku-4-5")
        self.assertIn("most capable model available", d.reason)

    @anthropic_up
    def test_context_requirement_excludes_small_window(self, _):
        # haiku is 200K; require 500K -> only sonnet/opus qualify; medium -> sonnet.
        d = self.router.route(
            RoutingRequest(
                complexity=TaskComplexity.MEDIUM, required_context_tokens=500_000
            )
        )
        self.assertEqual(d.model, "claude-sonnet-5")

    def test_offline_falls_back_to_stub(self):
        # No key -> anthropic unavailable -> only the stub is usable.
        d = self.router.route(RoutingRequest(complexity=TaskComplexity.HIGH))
        self.assertEqual(d.provider, "stub")

    @anthropic_up
    def test_no_model_when_context_impossible(self, _):
        with self.assertRaises(NoModelAvailable):
            self.router.route(
                RoutingRequest(required_context_tokens=5_000_000)
            )


class RouterFailoverTests(SimpleTestCase):
    @anthropic_up
    def test_complete_fails_over_to_next_candidate(self, _):
        router = ModelRouter()
        calls = []

        def fake_gateway(req, provider=None):
            calls.append((provider, req.model))
            if len(calls) == 1:
                raise ProviderUnavailable("primary down")
            return CompletionResponse(
                text="ok", model=req.model, provider=provider, usage=Usage()
            )

        with mock.patch(
            "apps.model_router.router.gateway_complete", side_effect=fake_gateway
        ):
            resp = router.complete(
                RoutingRequest(complexity=TaskComplexity.MEDIUM),
                messages=[Message("user", "hi")],
            )
        self.assertEqual(resp.text, "ok")
        self.assertEqual(len(calls), 2)  # first failed, second succeeded

    def test_complete_offline_uses_stub(self):
        resp = ModelRouter().complete(
            RoutingRequest(complexity=TaskComplexity.LOW),
            messages=[Message("user", "hello")],
        )
        self.assertEqual(resp.provider, "stub")
        self.assertIn("hello", resp.text)


class ModelRouterAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="dev@x.com", password="pw12345!")

    def test_model_list_requires_auth(self):
        self.assertEqual(
            self.client.get(reverse("model_router:model-list")).status_code, 403
        )

    def test_model_list_returns_catalog(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("model_router:model-list"))
        self.assertEqual(resp.status_code, 200)
        models = {m["model"] for m in resp.json()}
        self.assertIn("claude-opus-5", models)
        self.assertIn("stub-1", models)

    @anthropic_up
    def test_route_endpoint_returns_decision(self, _):
        self.client.force_login(self.user)
        resp = self.client.post(
            reverse("model_router:route"),
            {"complexity": "high"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["model"], "claude-opus-5")
        self.assertTrue(body["fallbacks"])

    def test_route_endpoint_requires_auth(self):
        resp = self.client.post(
            reverse("model_router:route"),
            {"complexity": "low"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)
