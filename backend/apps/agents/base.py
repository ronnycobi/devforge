"""The executable agent contract.

`BaseAgent` is what the Orchestrator (Phase 5) will drive. It defines the
input/output shapes and — importantly — the enforced execution boundary:

- capability checks (`require`) so an agent cannot perform an action it wasn't
  granted, and
- `run()`, which never lets an agent exception escape as a raw crash; it always
  returns a structured `AgentResult` the Orchestrator can record and act on.

Concrete specialist agents (Backend, Frontend, …) arrive once AI providers exist
(Phase 6). Each will bind to its catalog entry in apps.agents.definitions so its
declared capabilities and its enforced capabilities are the same set. This phase
ships the contract, the catalog, and the enforcement — not agent behaviour.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from apps.agents.capabilities import Capability


class AgentStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


class CapabilityDenied(Exception):
    """Raised when an agent attempts an action outside its granted capabilities."""

    def __init__(self, agent_key: str, capability: Capability):
        self.agent_key = agent_key
        self.capability = capability
        super().__init__(
            f"Agent '{agent_key}' lacks capability '{capability.value}'"
        )


@dataclass
class AgentContext:
    """Everything an agent needs to do one unit of work."""

    input: dict = field(default_factory=dict)
    project_id: int | None = None
    workspace_id: int | None = None
    actor_id: int | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class AgentResult:
    """Structured outcome of an agent run."""

    agent_key: str
    status: AgentStatus
    output: dict = field(default_factory=dict)
    messages: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == AgentStatus.COMPLETED

    @classmethod
    def completed(cls, agent_key, output=None, messages=None):
        return cls(
            agent_key=agent_key,
            status=AgentStatus.COMPLETED,
            output=output or {},
            messages=messages or [],
        )

    @classmethod
    def failed(cls, agent_key, error, messages=None):
        return cls(
            agent_key=agent_key,
            status=AgentStatus.FAILED,
            error=error,
            messages=messages or [],
        )


class BaseAgent:
    # Populated by concrete subclasses, or derived from a bound AgentDefinition.
    key: str = ""
    name: str = ""
    description: str = ""
    capabilities: frozenset[Capability] = frozenset()

    def has_capability(self, capability: Capability) -> bool:
        return capability in self.capabilities

    def require(self, capability: Capability) -> None:
        """Assert this agent holds `capability`, else raise CapabilityDenied."""
        if capability not in self.capabilities:
            raise CapabilityDenied(self.key, capability)

    def run(self, context: AgentContext) -> AgentResult:
        """Execute within a boundary that turns failures into structured results."""
        try:
            result = self.execute(context)
        except CapabilityDenied as exc:
            return AgentResult.failed(
                self.key, error=str(exc), messages=["capability denied"]
            )
        except Exception as exc:  # boundary: report, never crash the orchestrator
            return AgentResult.failed(self.key, error=str(exc))

        if not isinstance(result, AgentResult):
            raise TypeError(
                f"{type(self).__name__}.execute must return an AgentResult"
            )
        return result

    def execute(self, context: AgentContext) -> AgentResult:
        """Do the agent's actual work. Implemented by concrete agents (Phase 6+)."""
        raise NotImplementedError(
            f"Agent '{self.key or type(self).__name__}' has no executable "
            "behaviour yet; specialist agents are implemented once AI providers "
            "land (see docs/PRODUCT.md, Phases 6–15)."
        )
