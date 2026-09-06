"""AgentTask — the durable unit of orchestrated work.

Every field the Orchestrator needs to resume after a restart lives in the
database (docs/PRODUCT.md §2). The status field is a state machine: transitions
are validated so a task can never jump to an impossible state, and the small set
of high-level methods (start/complete/fail/...) are the only intended way to move
a task through its lifecycle. `agent_key` references the code-defined agent
catalog by key rather than a DB row, because agents are platform code.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class TaskStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    PLANNING = "planning", "Planning"
    RUNNING = "running", "Running"
    WAITING_FOR_TOOL = "waiting_for_tool", "Waiting for tool"
    WAITING_FOR_AGENT = "waiting_for_agent", "Waiting for agent"
    WAITING_FOR_APPROVAL = "waiting_for_approval", "Waiting for approval"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"
    TIMEOUT = "timeout", "Timeout"
    BLOCKED = "blocked", "Blocked"


TERMINAL_STATUSES = frozenset(
    {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.TIMEOUT,
    }
)

# In-flight states that a crash can leave stranded; recovery requeues them.
INTERRUPTIBLE_STATUSES = frozenset(
    {
        TaskStatus.PLANNING,
        TaskStatus.RUNNING,
        TaskStatus.WAITING_FOR_TOOL,
        TaskStatus.WAITING_FOR_AGENT,
    }
)

# Allowed status transitions. Anything not listed is rejected.
_TRANSITIONS: dict[str, set[str]] = {
    TaskStatus.QUEUED: {
        TaskStatus.PLANNING,
        TaskStatus.RUNNING,
        TaskStatus.WAITING_FOR_APPROVAL,
        TaskStatus.BLOCKED,
        TaskStatus.CANCELLED,
        TaskStatus.FAILED,  # pre-run checks (e.g. insufficient credits)
    },
    TaskStatus.BLOCKED: {
        TaskStatus.QUEUED,
        TaskStatus.PLANNING,
        TaskStatus.RUNNING,
        TaskStatus.CANCELLED,
        TaskStatus.FAILED,  # pre-run checks (e.g. insufficient credits)
    },
    TaskStatus.WAITING_FOR_APPROVAL: {TaskStatus.QUEUED, TaskStatus.CANCELLED},
    TaskStatus.PLANNING: {
        TaskStatus.RUNNING,
        TaskStatus.WAITING_FOR_TOOL,
        TaskStatus.WAITING_FOR_AGENT,
        TaskStatus.QUEUED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.RUNNING: {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.TIMEOUT,
        TaskStatus.WAITING_FOR_TOOL,
        TaskStatus.WAITING_FOR_AGENT,
        TaskStatus.QUEUED,  # retry
        TaskStatus.CANCELLED,
    },
    TaskStatus.WAITING_FOR_TOOL: {
        TaskStatus.RUNNING,
        TaskStatus.QUEUED,  # recovery after interruption
        TaskStatus.FAILED,
        TaskStatus.TIMEOUT,
        TaskStatus.CANCELLED,
    },
    TaskStatus.WAITING_FOR_AGENT: {
        TaskStatus.RUNNING,
        TaskStatus.QUEUED,  # recovery after interruption
        TaskStatus.FAILED,
        TaskStatus.TIMEOUT,
        TaskStatus.CANCELLED,
    },
    # Terminal states have no outgoing transitions.
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.CANCELLED: set(),
    TaskStatus.TIMEOUT: set(),
}


class InvalidTransition(Exception):
    def __init__(self, current, target):
        self.current = current
        self.target = target
        super().__init__(f"Cannot transition task from '{current}' to '{target}'")


class AgentTask(models.Model):
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        related_name="agent_tasks",
    )
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agent_tasks",
    )
    agent_key = models.CharField(max_length=64)
    parent_task = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="subtasks",
    )
    depends_on = models.ManyToManyField(
        "self",
        symmetrical=False,
        blank=True,
        related_name="dependents",
    )

    status = models.CharField(
        max_length=32, choices=TaskStatus.choices, default=TaskStatus.QUEUED
    )
    priority = models.IntegerField(default=0)

    input = models.JSONField(default=dict, blank=True)
    output = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    messages = models.JSONField(default=list, blank=True)

    # Retries
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=1)

    # Approval gate
    approval_required = models.BooleanField(default=False)
    approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_tasks",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    # AI usage / cost (populated once agents actually run — Phase 6+)
    model = models.CharField(max_length=100, blank=True)
    tokens = models.PositiveIntegerField(default=0)
    credits = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    cost = models.DecimalField(max_digits=12, decimal_places=4, default=0)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_tasks",
    )
    created_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-priority", "created_at"]
        indexes = [
            models.Index(fields=["project", "status"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"Task #{self.pk} [{self.agent_key}] {self.status}"

    # --- state machine ----------------------------------------------------

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def can_transition_to(self, target: str) -> bool:
        return target in _TRANSITIONS.get(self.status, set())

    def _transition(self, target: str, *, extra_fields=None):
        if not self.can_transition_to(target):
            raise InvalidTransition(self.status, target)
        self.status = target
        update = ["status"]
        if extra_fields:
            update += extra_fields
        self.save(update_fields=update)

    def start(self):
        """Move into RUNNING, stamp the first start, count the attempt."""
        self.attempts += 1
        if self.started_at is None:
            self.started_at = timezone.now()
        self._transition(TaskStatus.RUNNING, extra_fields=["attempts", "started_at"])

    def complete(self, output=None, messages=None, model="", tokens=0):
        self.output = output or {}
        if messages is not None:
            self.messages = messages
        if model:
            self.model = model
        if tokens:
            self.tokens = tokens
        self.completed_at = timezone.now()
        self._transition(
            TaskStatus.COMPLETED,
            extra_fields=["output", "messages", "model", "tokens", "completed_at"],
        )

    def fail(self, error, messages=None):
        self.error = error or ""
        if messages is not None:
            self.messages = messages
        self.completed_at = timezone.now()
        self._transition(
            TaskStatus.FAILED, extra_fields=["error", "messages", "completed_at"]
        )

    def requeue(self, error=""):
        """Return a running task to the queue for another attempt."""
        self.error = error or ""
        self._transition(TaskStatus.QUEUED, extra_fields=["error"])

    def block(self):
        self._transition(TaskStatus.BLOCKED)

    def await_approval(self):
        self._transition(TaskStatus.WAITING_FOR_APPROVAL)

    def resume_from_approval(self):
        """Return an approved, previously-gated task to the queue."""
        self._transition(TaskStatus.QUEUED)

    def cancel(self):
        self.completed_at = timezone.now()
        self._transition(TaskStatus.CANCELLED, extra_fields=["completed_at"])

    def timeout(self):
        self.completed_at = timezone.now()
        self._transition(TaskStatus.TIMEOUT, extra_fields=["completed_at"])
