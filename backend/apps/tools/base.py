"""Tool base types for DevForge's Tool Registry.

A Tool is a capability-gated operation surface an agent can invoke — the formal
seam between an agent and the outside world (files, git, sandbox, tests, …).
Every tool declares the least-privilege capabilities it requires; the Toolbelt
(registry.py) enforces them at a single invocation choke point, so an agent can
only use what its capabilities permit and every use is auditable in one place.

Tools expose ONE machine-readable entrypoint — execute(project, action, **kwargs)
returning a ToolResult — rather than ad-hoc methods, so the orchestrator can drive
them uniformly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from apps.agents.capabilities import Capability


class ToolError(Exception):
    pass


class ToolNotFound(ToolError):
    pass


class ToolPermissionDenied(ToolError):
    """Raised when an agent invokes a tool without the required capabilities."""


class UnknownAction(ToolError):
    pass


@dataclass
class ToolResult:
    ok: bool
    data: object = None
    error: str = ""

    @classmethod
    def success(cls, data=None) -> "ToolResult":
        return cls(ok=True, data=data)

    @classmethod
    def failed(cls, error: str) -> "ToolResult":
        return cls(ok=False, error=error)


class Tool:
    """Base class. Subclasses set name/description/required/actions and implement
    _run(project, action, **kwargs)."""

    name: str = ""
    description: str = ""
    required: frozenset[Capability] = frozenset()
    actions: frozenset[str] = frozenset()

    def permitted_by(self, capabilities: Iterable[Capability]) -> bool:
        return self.required <= set(capabilities)

    def execute(self, project, action: str, **kwargs) -> ToolResult:
        if action not in self.actions:
            raise UnknownAction(f"{self.name}: unknown action '{action}'")
        return self._run(project, action, **kwargs)

    def _run(self, project, action: str, **kwargs) -> ToolResult:  # pragma: no cover
        raise NotImplementedError

    def describe(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "required": sorted(c.value for c in self.required),
            "actions": sorted(self.actions),
        }
