"""In-process registry of agent definitions.

The agent catalog is platform code, not tenant data — it's the authoritative
list of which agents exist and what each is allowed to touch. The Orchestrator
(Phase 5) looks agents up here by key. Keep it a plain registry (like Django's
own app registry); agent *runs* are the DB-backed part and belong to Phase 5.
"""
from __future__ import annotations

from dataclasses import dataclass

from apps.agents.capabilities import Capability


@dataclass(frozen=True)
class AgentDefinition:
    key: str
    name: str
    description: str
    capabilities: frozenset[Capability]

    @property
    def capability_values(self) -> list[str]:
        return sorted(c.value for c in self.capabilities)


class AgentRegistry:
    def __init__(self):
        self._agents: dict[str, AgentDefinition] = {}

    def register(self, definition: AgentDefinition) -> AgentDefinition:
        if definition.key in self._agents:
            raise ValueError(f"Agent '{definition.key}' is already registered")
        self._agents[definition.key] = definition
        return definition

    def get(self, key: str) -> AgentDefinition:
        return self._agents[key]

    def all(self) -> list[AgentDefinition]:
        return list(self._agents.values())

    def keys(self) -> list[str]:
        return list(self._agents.keys())

    def __contains__(self, key: str) -> bool:
        return key in self._agents

    def __len__(self) -> int:
        return len(self._agents)
