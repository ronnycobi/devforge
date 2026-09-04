"""Registry of *executable* agent implementations.

This is distinct from the definition catalog (definitions.py): the catalog says
which agents exist and what each may do; this maps an agent key to the code that
actually runs it. It is empty until specialist agents are implemented (Phase 6+),
so resolving a key today raises NoExecutableAgent — which lets the Orchestrator
record an honest failure instead of fabricating a result. Once real agents land,
each registers its BaseAgent subclass here.
"""
from __future__ import annotations

from apps.agents.base import BaseAgent

_RUNNERS: dict[str, type[BaseAgent]] = {}


class NoExecutableAgent(Exception):
    """No executable implementation is registered for an agent key."""

    def __init__(self, key: str):
        self.key = key
        super().__init__(
            f"No executable implementation for agent '{key}' "
            "(specialist agents are implemented in Phase 6+)."
        )


def register_runner(agent_cls: type[BaseAgent]) -> type[BaseAgent]:
    if not agent_cls.key:
        raise ValueError("Executable agents must define a non-empty key")
    if agent_cls.key in _RUNNERS:
        raise ValueError(f"Runner for '{agent_cls.key}' already registered")
    _RUNNERS[agent_cls.key] = agent_cls
    return agent_cls


def has_runner(key: str) -> bool:
    return key in _RUNNERS


def resolve_agent(key: str) -> BaseAgent:
    """Return a fresh agent instance for `key`, or raise NoExecutableAgent."""
    try:
        return _RUNNERS[key]()
    except KeyError:
        raise NoExecutableAgent(key)
