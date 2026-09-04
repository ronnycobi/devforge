"""The Agent Orchestrator.

Coordinates agent work: creates tasks, decides what's runnable given dependencies
and approvals, drives BaseAgent.run() inside the task state machine, records
results/retries, and recovers in-flight tasks after a restart. It is the only
thing that runs agents — agents never invoke each other (docs/PRODUCT.md §2).

Execution is synchronous here. A worker/queue (Celery) is a later concern; the
orchestrator is written so that concern is just "who calls run_task", not a
rewrite — all state lives in AgentTask.
"""
from __future__ import annotations

from django.utils import timezone

from apps.agents.base import AgentContext
from apps.agents.definitions import registry
from apps.agents.runners import NoExecutableAgent, resolve_agent
from apps.orchestrator.models import AgentTask, TaskStatus


class Orchestrator:
    def __init__(self, resolver=resolve_agent):
        # `resolver(agent_key) -> BaseAgent`. Injectable so tests can supply a
        # fixture agent; defaults to the executable-agent registry (empty until
        # Phase 6, so real agent keys resolve to an honest failure for now).
        self.resolver = resolver

    # --- creation ---------------------------------------------------------

    def create_task(
        self,
        *,
        project,
        agent_key,
        input=None,
        workspace=None,
        parent_task=None,
        priority=0,
        approval_required=False,
        max_attempts=1,
        created_by=None,
        depends_on=None,
    ) -> AgentTask:
        if agent_key not in registry:
            raise ValueError(f"Unknown agent '{agent_key}'")
        task = AgentTask.objects.create(
            project=project,
            agent_key=agent_key,
            input=input or {},
            workspace=workspace,
            parent_task=parent_task,
            priority=priority,
            approval_required=approval_required,
            max_attempts=max_attempts,
            created_by=created_by,
        )
        if depends_on:
            task.depends_on.set(depends_on)
        return task

    # --- scheduling -------------------------------------------------------

    def dependencies_satisfied(self, task: AgentTask) -> bool:
        return all(
            dep.status == TaskStatus.COMPLETED for dep in task.depends_on.all()
        )

    def next_runnable(self, project) -> AgentTask | None:
        """The highest-priority task ready to run in `project`, or None."""
        candidates = AgentTask.objects.filter(
            project=project,
            status__in=[TaskStatus.QUEUED, TaskStatus.BLOCKED],
        ).order_by("-priority", "created_at")
        for task in candidates:
            if task.approval_required and not task.approved:
                continue
            if self.dependencies_satisfied(task):
                return task
        return None

    def run_ready(self, project, *, limit=1000) -> list[AgentTask]:
        """Drain runnable tasks (respecting dependencies) until none remain."""
        processed = []
        for _ in range(limit):
            task = self.next_runnable(project)
            if task is None:
                break
            self.run_task(task)
            processed.append(task)
        return processed

    # --- execution --------------------------------------------------------

    def run_task(self, task: AgentTask) -> AgentTask:
        task.refresh_from_db()

        if task.is_terminal:
            return task

        # Approval gate: hold until a human approves.
        if task.approval_required and not task.approved:
            if task.status != TaskStatus.WAITING_FOR_APPROVAL and task.can_transition_to(
                TaskStatus.WAITING_FOR_APPROVAL
            ):
                task.await_approval()
            return task

        # Dependency gate: block until predecessors complete.
        if not self.dependencies_satisfied(task):
            if task.status != TaskStatus.BLOCKED and task.can_transition_to(
                TaskStatus.BLOCKED
            ):
                task.block()
            return task

        # Only QUEUED/BLOCKED tasks are startable at this point.
        if task.status not in (TaskStatus.QUEUED, TaskStatus.BLOCKED):
            return task

        task.start()

        if task.agent_key not in registry:
            return self._handle_failure(task, f"Unknown agent '{task.agent_key}'")

        try:
            agent = self.resolver(task.agent_key)
        except NoExecutableAgent as exc:
            return self._handle_failure(task, str(exc))

        context = AgentContext(
            input=task.input,
            project_id=task.project_id,
            workspace_id=task.workspace_id,
            actor_id=task.created_by_id,
            metadata={"task_id": task.id},
        )
        result = agent.run(context)  # BaseAgent.run never raises

        if result.ok:
            task.complete(
                output=result.output,
                messages=result.messages,
                model=result.model,
                tokens=result.usage_tokens,
            )
        else:
            return self._handle_failure(
                task, result.error or "agent failed", messages=result.messages
            )
        return task

    def _handle_failure(self, task, error, messages=None):
        if task.attempts < task.max_attempts:
            task.requeue(error=error)  # another attempt remains
        else:
            task.fail(error, messages=messages)
        return task

    # --- approvals & cancellation ----------------------------------------

    def approve(self, task: AgentTask, user) -> AgentTask:
        task.refresh_from_db()
        task.approved = True
        task.approved_by = user
        task.approved_at = timezone.now()
        task.save(update_fields=["approved", "approved_by", "approved_at"])
        if task.status == TaskStatus.WAITING_FOR_APPROVAL:
            task.resume_from_approval()
        return task

    def cancel(self, task: AgentTask) -> AgentTask:
        task.refresh_from_db()
        if not task.is_terminal and task.can_transition_to(TaskStatus.CANCELLED):
            task.cancel()
        return task

    # --- resumability -----------------------------------------------------

    def recover_interrupted(self, project=None) -> list[AgentTask]:
        """Requeue tasks left in-flight by a crash/restart.

        All task state is durable, so recovery just means moving stranded
        in-flight tasks back to QUEUED to be picked up again.
        """
        from apps.orchestrator.models import INTERRUPTIBLE_STATUSES

        qs = AgentTask.objects.filter(status__in=INTERRUPTIBLE_STATUSES)
        if project is not None:
            qs = qs.filter(project=project)
        recovered = []
        for task in qs:
            task.requeue(error="recovered after interruption")
            recovered.append(task)
        return recovered
