from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.costs.estimator import estimate_project, model_for_complexity
from apps.model_router.router import TaskComplexity
from apps.organizations.models import Organization
from apps.projects.models import Project

User = get_user_model()


class ModelSelectionTests(SimpleTestCase):
    def test_picks_real_model_not_stub(self):
        for complexity in TaskComplexity:
            profile = model_for_complexity(complexity)
            self.assertIsNotNone(profile)
            self.assertFalse(profile.is_fallback_only)

    def test_high_complexity_gets_top_tier(self):
        self.assertEqual(model_for_complexity(TaskComplexity.HIGH).model, "claude-opus-5")

    def test_medium_gets_cheapest_sufficient(self):
        self.assertEqual(
            model_for_complexity(TaskComplexity.MEDIUM).model, "claude-sonnet-5"
        )


class EstimateTests(SimpleTestCase):
    def test_returns_ranges_and_recommendation(self):
        est = estimate_project()
        low, high = est["cost_usd"]
        self.assertLess(low, high)  # a real range, not a point
        self.assertLess(est["credits"][0], est["credits"][1])
        self.assertIn(est["risk"], {"low", "medium", "high"})
        self.assertIn(est["recommended_plan"], {"free", "pro", "business", "enterprise"})
        self.assertEqual(len(est["per_agent"]), 7)

    def test_estimate_is_nonzero_offline(self):
        # Uses catalog pricing directly, so it doesn't collapse to the free stub.
        est = estimate_project(["architect"])
        self.assertGreater(est["cost_usd"][1], 0)

    def test_more_iterations_cost_more(self):
        one = estimate_project(["backend"], iterations=1)["cost_usd"][1]
        three = estimate_project(["backend"], iterations=3)["cost_usd"][1]
        self.assertGreater(three, one)

    def test_full_pipeline_is_higher_risk(self):
        self.assertIn(estimate_project()["risk"], {"medium", "high"})


class CostEstimateAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="u@x.com", password="pw12345!")
        self.org = Organization.objects.create(name="Acme")
        self.org.add_member(self.user)
        self.project = Project.objects.create(organization=self.org, name="App")
        self.other = Project.objects.create(
            organization=Organization.objects.create(name="Other"), name="B"
        )

    def test_estimate_endpoint(self):
        self.client.force_login(self.user)
        resp = self.client.post(
            reverse("costs:estimate", args=[self.project.id]),
            {"iterations": 2},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["iterations"], 2)
        self.assertIn("recommended_plan", resp.json())

    def test_requires_auth(self):
        resp = self.client.post(reverse("costs:estimate", args=[self.project.id]))
        self.assertEqual(resp.status_code, 403)

    def test_foreign_project_404(self):
        self.client.force_login(self.user)
        resp = self.client.post(reverse("costs:estimate", args=[self.other.id]))
        self.assertEqual(resp.status_code, 404)
