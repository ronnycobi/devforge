import json
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.changes import service as svc
from apps.changes.models import ChangeRequest, ChangeStatus
from apps.changes.planner import plan_change
from apps.organizations.models import Organization, Role
from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.projects.models import Project

User = get_user_model()

PLAN_JSON = json.dumps({
    "summary": "Add PayFast payments to checkout.",
    "affected_areas": {
        "database": ["Payment model"],
        "backend": ["PayFast client", "checkout endpoint"],
        "frontend": ["Payment button"],
        "testing": ["Payment tests"],
    },
    "steps": ["Add Payment model", "Integrate PayFast", "Wire checkout", "Add tests"],
    "risk": "high",
    "requires_approval": True,
})


def _fake(text, model="claude-opus-5"):
    from apps.ai_providers.base import CompletionResponse, Usage

    def _inner(request, provider=None):
        return CompletionResponse(text=text, model=model, provider="anthropic", usage=Usage(80, 200))
    return _inner


def _sequence(*texts, model="claude-opus-5"):
    from apps.ai_providers.base import CompletionResponse, Usage
    calls = {"n": 0}

    def _inner(request, provider=None):
        i = min(calls["n"], len(texts) - 1)
        calls["n"] += 1
        return CompletionResponse(text=texts[i], model=model, provider="anthropic", usage=Usage(80, 200))
    return _inner


MIGRATION_JSON = json.dumps({
    "operation": "create",
    "description": "Add payments table",
    "up_sql": "CREATE TABLE payments (id SERIAL PRIMARY KEY, amount NUMERIC)",
    "down_sql": "DROP TABLE payments",
})

DROP_MIGRATION_JSON = json.dumps({
    "operation": "drop",
    "description": "Remove legacy table",
    "up_sql": "DROP TABLE legacy",
    "down_sql": "",
})


class OutcomeTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.user = User.objects.create_user(email="o@a.com", password="x")
        self.project = Project.objects.create(organization=self.org, name="Store")

    def test_summary_reports_failure_faithfully(self):
        from apps.changes.service import _summarize_tasks
        from apps.orchestrator.models import TaskStatus
        from apps.orchestrator.service import Orchestrator
        orch = Orchestrator()
        t1 = orch.create_task(project=self.project, agent_key="backend", input={})
        t2 = orch.create_task(project=self.project, agent_key="testing", input={})
        t1.status = TaskStatus.COMPLETED
        t1.output = {"files_generated": 2, "verified": True}
        t1.save(update_fields=["status", "output"])
        t2.status = TaskStatus.FAILED
        t2.error = "boom"
        t2.save(update_fields=["status", "error"])

        res = _summarize_tasks([t1.id, t2.id])
        self.assertFalse(res["ok"])
        self.assertEqual(res["failed"], ["testing"])
        self.assertEqual(res["completed"], 1)
        self.assertEqual(res["total"], 2)

    def test_implement_records_done_outcome(self):
        # A project with some design context so code_review has something to review.
        ProjectContext(self.project).set(
            ContextKind.REQUIREMENT, "widget", title="Widget", content="Show a widget"
        )
        change = svc.create_change(self.project, "Add a widget", self.user)
        change.plan = {"affected_areas": {"backend": ["widget"]}, "risk": "low"}
        change.requires_approval = False
        change.save()
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                svc.implement(change)  # offline: backend + code_review complete
        change.refresh_from_db()
        self.assertEqual(change.status, ChangeStatus.DONE)
        self.assertTrue(change.result["ok"])
        self.assertEqual(change.result["total"], 2)  # backend + code_review


class MigrationWiringTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.user = User.objects.create_user(email="o@a.com", password="x")
        self.project = Project.objects.create(
            organization=self.org, name="Store", technology={"database": "postgresql"}
        )

    def _plan(self, *texts):
        change = svc.create_change(self.project, "Add payments", self.user)
        with mock.patch("apps.model_router.router.gateway_complete", side_effect=_sequence(*texts)):
            return svc.build_plan(change)

    def test_database_change_plans_a_migration(self):
        change = self._plan(PLAN_JSON, MIGRATION_JSON)
        self.assertIsNotNone(change.migration)
        self.assertEqual(change.migration.operation, "create")
        self.assertIn("CREATE TABLE payments", change.migration.up_sql)
        self.assertEqual(change.migration.database_id, "postgresql")

    def test_destructive_migration_forces_change_approval(self):
        low_plan = json.dumps({
            "summary": "drop legacy", "affected_areas": {"database": ["drop legacy table"]},
            "steps": ["s"], "risk": "low", "requires_approval": False,
        })
        change = self._plan(low_plan, DROP_MIGRATION_JSON)
        self.assertTrue(change.migration.requires_approval)     # DROP → HIGH risk
        self.assertTrue(change.requires_approval)               # elevated the change gate
        self.assertEqual(change.status, ChangeStatus.AWAITING_APPROVAL)

    def test_offline_plans_no_migration(self):
        change = svc.create_change(self.project, "Add payments", self.user)
        svc.build_plan(change)  # stub → empty plan → no database area → no migration
        self.assertIsNone(change.migration)

    def test_non_database_change_has_no_migration(self):
        fe_plan = json.dumps({
            "summary": "button", "affected_areas": {"frontend": ["Pay button"]},
            "steps": ["s"], "risk": "low", "requires_approval": False,
        })
        change = self._plan(fe_plan)
        self.assertIsNone(change.migration)

    def test_approving_change_approves_its_migration(self):
        change = self._plan(PLAN_JSON, MIGRATION_JSON)
        svc.approve(change, self.user)
        change.migration.refresh_from_db()
        self.assertTrue(change.migration.approved)

    def test_non_migration_engine_plans_no_migration(self):
        self.project.technology = {"database": "redis"}
        self.project.save(update_fields=["technology"])
        change = self._plan(PLAN_JSON, MIGRATION_JSON)
        self.assertIsNone(change.migration)  # Redis has no schema migrations


class PlannerTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(organization=self.org, name="Store")

    def test_plan_parses_impact(self):
        with mock.patch("apps.model_router.router.gateway_complete", side_effect=_fake(PLAN_JSON)):
            plan = plan_change("Add PayFast", "some twin")
        self.assertEqual(plan["risk"], "high")
        self.assertIn("database", plan["affected_areas"])
        self.assertTrue(plan["requires_approval"])

    def test_offline_plan_is_empty_not_fabricated(self):
        plan = plan_change("Add PayFast", "some twin")  # stub -> no JSON
        self.assertEqual(plan["affected_areas"], {})


class ChangeFlowTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(organization=self.org, name="Store")
        self.user = User.objects.create_user(email="o@x.com", password="pw12345!")
        self.org.add_member(self.user, role=Role.OWNER)
        ProjectContext(self.project).set(
            ContextKind.ARCHITECTURE, "api", title="API", content="Django backend"
        )

    def test_significant_change_awaits_approval_then_implements(self):
        change = svc.create_change(self.project, "Add PayFast payments", self.user)
        with mock.patch("apps.model_router.router.gateway_complete", side_effect=_fake(PLAN_JSON)):
            svc.build_plan(change)
        change.refresh_from_db()
        self.assertEqual(change.status, ChangeStatus.AWAITING_APPROVAL)
        self.assertTrue(change.estimate["agents"])  # estimate computed from impact
        self.assertGreater(change.estimate["credits"][1], 0)

        # Cannot implement while gated.
        svc.implement(change)
        change.refresh_from_db()
        self.assertEqual(change.status, ChangeStatus.AWAITING_APPROVAL)

        svc.approve(change, self.user)
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(DEVFORGE_WORKSPACES_ROOT=tmp):
                svc.implement(change)
        change.refresh_from_db()
        self.assertEqual(change.status, ChangeStatus.DONE)
        # Implemented by orchestrated agents against the SAME project.
        self.assertTrue(change.task_ids)
        agents = set(
            self.project.agent_tasks.filter(id__in=change.task_ids).values_list("agent_key", flat=True)
        )
        self.assertTrue({"database", "backend", "frontend", "testing", "code_review"} <= agents)

    def test_low_risk_change_needs_no_approval(self):
        low = json.dumps({"summary": "Tweak", "affected_areas": {"frontend": ["button"]},
                          "steps": [], "risk": "low", "requires_approval": False})
        change = svc.create_change(self.project, "Change a label", self.user)
        with mock.patch("apps.model_router.router.gateway_complete", side_effect=_fake(low)):
            svc.build_plan(change)
        change.refresh_from_db()
        self.assertEqual(change.status, ChangeStatus.PLANNED)
        self.assertFalse(change.requires_approval)


class ChangeUITests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="o@x.com", password="pw12345!")
        self.org = Organization.objects.create(name="Acme")
        self.org.add_member(self.owner, role=Role.OWNER)
        self.project = Project.objects.create(organization=self.org, name="Store")

    def test_request_change_via_ui_creates_and_plans(self):
        self.client.force_login(self.owner)
        with mock.patch("apps.model_router.router.gateway_complete", side_effect=_fake(PLAN_JSON)):
            resp = self.client.post(
                reverse("dashboard:project", args=[self.project.id]),
                {"action": "create_change", "description": "Add PayFast payments"},
            )
        self.assertEqual(resp.status_code, 302)
        change = ChangeRequest.objects.get(project=self.project)
        self.assertTrue(change.plan)
        # Detail page renders the impact plan.
        page = self.client.get(reverse("dashboard:change", args=[change.id]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Affected areas")
