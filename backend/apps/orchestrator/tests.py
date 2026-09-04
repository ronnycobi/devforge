from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.agents.base import AgentResult, BaseAgent
from apps.organizations.models import Organization, Role
from apps.orchestrator.models import AgentTask, InvalidTransition, TaskStatus
from apps.orchestrator.service import Orchestrator
from apps.projects.models import Project

User = get_user_model()


# --- fixture executable agents (not part of the shipped catalog) -------------


class _OkAgent(BaseAgent):
    key = "backend"  # a real catalog key so create_task validation passes

    def execute(self, context):
        return AgentResult.completed(
            self.key, output={"ran": True, "input": context.input}
        )


class _FailAgent(BaseAgent):
    key = "backend"

    def execute(self, context):
        return AgentResult.failed(self.key, error="nope")


def ok_resolver(key):
    return _OkAgent()


def fail_resolver(key):
    return _FailAgent()


class TaskStateMachineTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(organization=self.org, name="App")

    def _task(self, **kw):
        return AgentTask.objects.create(project=self.project, agent_key="backend", **kw)

    def test_illegal_transition_is_rejected(self):
        task = self._task()  # QUEUED
        with self.assertRaises(InvalidTransition):
            task.complete()  # QUEUED -> COMPLETED is not allowed

    def test_start_complete_lifecycle_stamps_times(self):
        task = self._task()
        task.start()
        self.assertEqual(task.status, TaskStatus.RUNNING)
        self.assertEqual(task.attempts, 1)
        self.assertIsNotNone(task.started_at)
        task.complete(output={"x": 1})
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertTrue(task.is_terminal)
        self.assertIsNotNone(task.completed_at)

    def test_cancel_from_queued(self):
        task = self._task()
        task.cancel()
        self.assertEqual(task.status, TaskStatus.CANCELLED)


class OrchestratorExecutionTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(organization=self.org, name="App")

    def _task(self, **kw):
        return Orchestrator().create_task(
            project=self.project, agent_key="backend", **kw
        )

    def test_successful_run_completes_with_output(self):
        task = self._task(input={"a": 1})
        Orchestrator(resolver=ok_resolver).run_task(task)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertEqual(task.output, {"ran": True, "input": {"a": 1}})

    def test_no_executable_agent_fails_honestly(self):
        # Default resolver has no implementations yet (Phase 6).
        task = self._task()
        Orchestrator().run_task(task)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIn("No executable implementation", task.error)
        self.assertEqual(task.attempts, 1)

    def test_failure_retries_up_to_max_attempts(self):
        task = self._task(max_attempts=2)
        orch = Orchestrator(resolver=fail_resolver)

        orch.run_task(task)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.QUEUED)  # requeued for retry
        self.assertEqual(task.attempts, 1)

        orch.run_task(task)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertEqual(task.attempts, 2)
        self.assertEqual(task.error, "nope")

    def test_unknown_agent_cannot_be_created(self):
        with self.assertRaises(ValueError):
            Orchestrator().create_task(project=self.project, agent_key="ghost")


class OrchestratorApprovalTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(organization=self.org, name="App")
        self.approver = User.objects.create_user(
            email="boss@x.com", password="pw12345!"
        )

    def test_task_waits_for_approval_then_runs(self):
        orch = Orchestrator(resolver=ok_resolver)
        task = orch.create_task(
            project=self.project, agent_key="backend", approval_required=True
        )

        orch.run_task(task)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.WAITING_FOR_APPROVAL)

        orch.approve(task, self.approver)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.QUEUED)
        self.assertTrue(task.approved)
        self.assertEqual(task.approved_by, self.approver)

        orch.run_task(task)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.COMPLETED)


class OrchestratorDependencyTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(organization=self.org, name="App")

    def test_dependent_task_blocks_until_predecessor_completes(self):
        orch = Orchestrator(resolver=ok_resolver)
        a = orch.create_task(project=self.project, agent_key="backend", priority=10)
        b = orch.create_task(project=self.project, agent_key="backend")
        b.depends_on.set([a])

        # A is runnable first; B is not.
        self.assertEqual(orch.next_runnable(self.project), a)

        # Attempting B directly while A is queued blocks it.
        orch.run_task(b)
        b.refresh_from_db()
        self.assertEqual(b.status, TaskStatus.BLOCKED)

    def test_run_ready_drains_the_graph_in_order(self):
        orch = Orchestrator(resolver=ok_resolver)
        a = orch.create_task(project=self.project, agent_key="backend", priority=10)
        b = orch.create_task(project=self.project, agent_key="backend")
        b.depends_on.set([a])

        orch.run_ready(self.project)
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual(a.status, TaskStatus.COMPLETED)
        self.assertEqual(b.status, TaskStatus.COMPLETED)


class OrchestratorRecoveryTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme")
        self.project = Project.objects.create(organization=self.org, name="App")

    def test_interrupted_running_task_is_requeued(self):
        orch = Orchestrator()
        task = orch.create_task(project=self.project, agent_key="backend")
        task.start()  # simulate a crash mid-run: left in RUNNING
        self.assertEqual(task.status, TaskStatus.RUNNING)

        recovered = orch.recover_interrupted(project=self.project)
        self.assertEqual(len(recovered), 1)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.QUEUED)


class TaskAPITests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(email="alice@x.com", password="pw12345!")
        self.carol = User.objects.create_user(email="carol@x.com", password="pw12345!")
        self.bob = User.objects.create_user(email="bob@x.com", password="pw12345!")

        self.org_a = Organization.objects.create(name="Org A")
        self.org_b = Organization.objects.create(name="Org B")
        self.org_a.add_member(self.alice, role=Role.OWNER)
        self.org_a.add_member(self.carol, role=Role.MEMBER)
        self.org_b.add_member(self.bob, role=Role.OWNER)

        self.proj_a = Project.objects.create(organization=self.org_a, name="A")
        self.proj_b = Project.objects.create(organization=self.org_b, name="B")

    def _list_url(self, project):
        return reverse("orchestrator:task-list", args=[project.id])

    def test_owner_creates_a_queued_task(self):
        self.client.force_login(self.alice)
        resp = self.client.post(
            self._list_url(self.proj_a),
            {"agent_key": "backend", "input": {"goal": "build"}},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body["status"], "queued")
        self.assertEqual(body["created_by"], self.alice.id)

    def test_member_cannot_create_task(self):
        self.client.force_login(self.carol)
        resp = self.client.post(
            self._list_url(self.proj_a),
            {"agent_key": "backend"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_unknown_agent_key_rejected(self):
        self.client.force_login(self.alice)
        resp = self.client.post(
            self._list_url(self.proj_a),
            {"agent_key": "ghost"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_cannot_list_foreign_project_tasks(self):
        self.client.force_login(self.alice)
        resp = self.client.get(self._list_url(self.proj_b))
        self.assertEqual(resp.status_code, 404)

    def test_cancel_action(self):
        task = Orchestrator().create_task(project=self.proj_a, agent_key="backend")
        self.client.force_login(self.alice)
        resp = self.client.post(reverse("orchestrator:task-cancel", args=[task.id]))
        self.assertEqual(resp.status_code, 200)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.CANCELLED)

    def test_approve_action_sets_approved(self):
        task = Orchestrator().create_task(
            project=self.proj_a, agent_key="backend", approval_required=True
        )
        self.client.force_login(self.alice)
        resp = self.client.post(reverse("orchestrator:task-approve", args=[task.id]))
        self.assertEqual(resp.status_code, 200)
        task.refresh_from_db()
        self.assertTrue(task.approved)

    def test_member_cannot_cancel(self):
        task = Orchestrator().create_task(project=self.proj_a, agent_key="backend")
        self.client.force_login(self.carol)
        resp = self.client.post(reverse("orchestrator:task-cancel", args=[task.id]))
        self.assertEqual(resp.status_code, 403)
