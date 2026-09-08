"""Tool Registry + Toolbelt.

The registry is the catalog of available tools. A Toolbelt binds a project and a
set of granted capabilities (an agent's) and is the single place tool permissions
are enforced: `invoke(tool, action, ...)` checks the tool's required capabilities
against the belt's grants before running it, so an agent can never use a tool it
isn't permitted to — mirroring the agent capability model, one level down.
"""
from __future__ import annotations

from apps.agents.capabilities import Capability
from apps.tools.base import Tool, ToolNotFound, ToolPermissionDenied, ToolResult


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' already registered")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)


registry = ToolRegistry()


class Toolbelt:
    """The set of tools an agent may use, given its capabilities, bound to a project."""

    def __init__(self, project, capabilities, tool_registry: ToolRegistry = None):
        self.project = project
        self.capabilities = frozenset(capabilities)
        self.registry = tool_registry or registry

    def available(self) -> list[Tool]:
        """Tools this belt is permitted to use (least privilege)."""
        return [t for t in self.registry.all() if t.permitted_by(self.capabilities)]

    def has(self, name: str) -> bool:
        tool = self.registry.get(name)
        return tool is not None and tool.permitted_by(self.capabilities)

    def invoke(self, name: str, action: str, **kwargs) -> ToolResult:
        """The single, enforced entrypoint for tool use."""
        tool = self.registry.get(name)
        if tool is None:
            raise ToolNotFound(f"No such tool '{name}'")
        if not tool.permitted_by(self.capabilities):
            missing = sorted(c.value for c in (tool.required - self.capabilities))
            raise ToolPermissionDenied(
                f"Tool '{name}' requires capabilities not granted: {', '.join(missing)}"
            )
        return tool.execute(self.project, action, **kwargs)
