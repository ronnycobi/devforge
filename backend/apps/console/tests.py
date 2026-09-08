"""Tests for the internal staff console.

Covers the access boundary (anonymous → login, customer → 403, staff → 200) and
that each page renders real cross-tenant data.
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.credits.models import CreditAccount, UsageRecord
from apps.marketing.models import ContactMessage
from apps.orchestrator.models import AgentTask, TaskStatus
from apps.organizations.models import Membership, Organization, Role
from apps.projects.models import Project


class ConsoleAccessTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(email="staff@devforge.local", password="x", is_staff=True)
        self.customer = User.objects.create_user(email="cust@acme.com", password="x")

    def test_anonymous_redirected_to_login(self):
        r = self.client.get(reverse("console:overview"))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("dashboard:login"), r.headers["Location"])

    def test_customer_forbidden(self):
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(reverse("console:overview")).status_code, 403)

    def test_staff_allowed(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("console:overview")).status_code, 200)

    def test_every_page_reachable_by_staff(self):
        self.client.force_login(self.staff)
        for name in ["overview", "orgs", "users", "projects", "tasks", "economics",
                     "deployments", "leads"]:
            self.assertEqual(self.client.get(reverse(f"console:{name}")).status_code, 200, name)


class ConsoleDataTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(email="staff@devforge.local", password="x", is_staff=True)
        self.owner = User.objects.create_user(email="owner@acme.com", password="x")
        self.org = Organization.objects.create(name="Acme Corp", created_by=self.owner)
        Membership.objects.create(organization=self.org, user=self.owner, role=Role.OWNER)
        self.project = Project.objects.create(organization=self.org, name="Billing App", created_by=self.owner)
        CreditAccount.objects.create(organization=self.org, plan="pro", balance=Decimal("4200"))
        self.task = AgentTask.objects.create(
            project=self.project, agent_key="backend", status=TaskStatus.COMPLETED,
            model="claude-sonnet-5", tokens=1200, cost=Decimal("0.0450"),
        )
        UsageRecord.objects.create(
            organization=self.org, project=self.project, agent_key="backend",
            provider="anthropic", model="claude-sonnet-5", total_tokens=1200,
            cost_usd=Decimal("0.045000"), credits_charged=Decimal("4.5"),
        )
        ContactMessage.objects.create(name="Jo Buyer", email="jo@lead.com", message="Interested in DevForge")
        self.client.force_login(self.staff)

    def test_overview_shows_platform_totals(self):
        r = self.client.get(reverse("console:overview"))
        self.assertContains(r, "Acme Corp")
        self.assertContains(r, "backend")  # recent task agent

    def test_org_list_and_detail(self):
        self.assertContains(self.client.get(reverse("console:orgs")), "Acme Corp")
        r = self.client.get(reverse("console:org", args=[self.org.id]))
        self.assertContains(r, "owner@acme.com")
        self.assertContains(r, "Billing App")

    def test_economics_aggregates_usage(self):
        r = self.client.get(reverse("console:economics"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "anthropic")

    def test_tasks_status_filter(self):
        r = self.client.get(reverse("console:tasks"), {"status": TaskStatus.COMPLETED})
        self.assertContains(r, "backend")
        r2 = self.client.get(reverse("console:tasks"), {"status": TaskStatus.FAILED})
        self.assertNotContains(r2, "Billing App")

    def test_leads_lists_contact_messages(self):
        self.assertContains(self.client.get(reverse("console:leads")), "jo@lead.com")


class ControlCenterTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(email="cc@devforge.local", password="x", is_staff=True)

    def test_overview_shows_health_and_kpis(self):
        self.client.force_login(self.staff)
        r = self.client.get(reverse("console:overview"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Control Center")
        self.assertContains(r, "System health")
        self.assertContains(r, "Success rate")
        self.assertContains(r, "Live activity")

    def test_health_probes_are_honest(self):
        from apps.console.health import system_health
        checks = {c["name"]: c for c in system_health()}
        self.assertEqual(checks["Database"]["status"], "ok")       # a real SELECT 1
        self.assertEqual(checks["Storage"]["status"], "ok")        # workspaces writable
        self.assertEqual(checks["Deployment"]["status"], "unknown")  # no live target — honest
