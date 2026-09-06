from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.ai_providers.base import CompletionResponse, Usage
from apps.credits.models import CreditAccount, UsageRecord
from apps.credits.services import (
    cost_usd_for,
    credits_for,
    ensure_account,
    guard_can_run,
    record_task_usage,
)
from apps.organizations.models import Organization
from apps.orchestrator.service import Orchestrator
from apps.projects.models import Project

User = get_user_model()


class CostAndCreditMathTests(TestCase):
    def test_cost_uses_model_pricing(self):
        # opus-5 blended avg = (5+25)/2 = 15 USD / Mtok
        cost = cost_usd_for("claude-opus-5", 1_000_000)
        self.assertEqual(cost, Decimal("15"))

    def test_stub_model_is_free(self):
        self.assertEqual(cost_usd_for("stub-1", 1_000_000), Decimal("0"))

    def test_credits_conversion(self):
        # default 100 credits per USD
        self.assertEqual(credits_for(Decimal("15")), Decimal("1500.0000"))


class GuardTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")

    def test_no_account_is_unlimited(self):
        self.assertTrue(guard_can_run(self.org))

    def test_positive_balance_allows(self):
        ensure_account(self.org, plan="free")  # grants 1000
        self.assertTrue(guard_can_run(self.org))

    def test_zero_balance_blocks(self):
        acct = ensure_account(self.org, plan="free", grant=False)  # balance 0
        self.assertFalse(guard_can_run(self.org))
        self.assertEqual(acct.balance, Decimal("0"))


class UsageRecordingTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(organization=self.org, name="App")

    def _fake(self, text, model):
        def _inner(request, provider=None):
            return CompletionResponse(
                text=text, model=model, provider="anthropic", usage=Usage(1000, 2000)
            )
        return _inner

    def test_completed_task_records_usage_and_debits(self):
        ensure_account(self.org, plan="pro")  # 5000 credits
        # A real requirements extraction so tokens/model are set on the task.
        import json
        reqs = json.dumps([{"title": "Login", "description": "Email", "acceptance_criteria": []}])
        with mock.patch(
            "apps.model_router.router.gateway_complete",
            side_effect=self._fake(reqs, "claude-opus-5"),
        ):
            orch = Orchestrator()
            task = orch.create_task(
                project=self.project, agent_key="requirements", input={"brief": "x"}
            )
            orch.run_task(task)
        task.refresh_from_db()
        self.assertEqual(task.status, "completed")

        rec = UsageRecord.objects.get(task=task)
        self.assertEqual(rec.model, "claude-opus-5")
        self.assertEqual(rec.total_tokens, 3000)
        self.assertGreater(rec.credits_charged, 0)

        acct = CreditAccount.objects.get(organization=self.org)
        self.assertEqual(acct.balance, Decimal("5000") - rec.credits_charged)

    def test_stub_usage_is_free(self):
        ensure_account(self.org, plan="free")
        orch = Orchestrator()
        task = orch.create_task(
            project=self.project, agent_key="requirements", input={"brief": "x"}
        )
        orch.run_task(task)  # offline stub
        task.refresh_from_db()
        rec = UsageRecord.objects.get(task=task)
        self.assertEqual(rec.credits_charged, Decimal("0"))
        self.assertEqual(CreditAccount.objects.get(organization=self.org).balance, 1000)


class BudgetProtectionTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(organization=self.org, name="App")

    def test_depleted_account_blocks_task(self):
        ensure_account(self.org, plan="free", grant=False)  # balance 0
        orch = Orchestrator()
        task = orch.create_task(
            project=self.project, agent_key="requirements", input={"brief": "x"}
        )
        orch.run_task(task)
        task.refresh_from_db()
        self.assertEqual(task.status, "failed")
        self.assertIn("Insufficient credits", task.error)
        self.assertEqual(task.attempts, 0)  # never started


class CreditsAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="u@x.com", password="pw12345!")
        self.org = Organization.objects.create(name="Acme")
        self.org.add_member(self.user)

    def test_balance_unlimited_without_account(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("credits:balance", args=[self.org.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["unlimited"])

    def test_balance_with_account(self):
        ensure_account(self.org, plan="pro")
        self.client.force_login(self.user)
        resp = self.client.get(reverse("credits:balance", args=[self.org.id]))
        self.assertEqual(resp.json()["plan"], "pro")
        self.assertEqual(resp.json()["balance"], "5000.0000")

    def test_non_member_cannot_read(self):
        other = User.objects.create_user(email="z@x.com", password="pw12345!")
        self.client.force_login(other)
        resp = self.client.get(reverse("credits:balance", args=[self.org.id]))
        self.assertEqual(resp.status_code, 404)
