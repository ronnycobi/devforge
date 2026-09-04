"""Architect Agent — designs the system architecture from the requirements.

Reads the project's requirements from context, asks a model (HIGH complexity, so
the router reaches for a capable model) for components and technical decisions,
and persists them back as ARCHITECTURE and TECH_DECISION context entries. Uses
keyed upsert (by component/decision name) so re-running refines the design in
place rather than duplicating it. Declares/enforces only read-requirements +
read/write-architecture.
"""
from __future__ import annotations

from django.utils.text import slugify

from apps.agents.base import AgentContext, AgentResult, BaseAgent
from apps.agents.capabilities import Capability
from apps.agents.definitions import ARCHITECT
from apps.agents.runners import register_runner
from apps.ai_providers.base import Message
from apps.architecture.parsing import parse_architecture
from apps.architecture.prompts import SYSTEM_PROMPT, build_user_prompt
from apps.model_router.router import ModelRouter, RoutingRequest, TaskComplexity
from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.projects.models import Project


class ArchitectAgent(BaseAgent):
    key = ARCHITECT.key
    name = ARCHITECT.name
    description = ARCHITECT.description
    capabilities = ARCHITECT.capabilities

    def __init__(self, router: ModelRouter | None = None):
        self.router = router or ModelRouter()

    def execute(self, context: AgentContext) -> AgentResult:
        self.require(Capability.WRITE_ARCHITECTURE)

        if not context.project_id:
            return AgentResult.failed(self.key, "Architecture work needs a project.")

        project = Project.objects.get(id=context.project_id)
        ctx = ProjectContext(project)
        requirements_digest = ctx.digest(
            kinds=[ContextKind.REQUIREMENT, ContextKind.BUSINESS_RULE],
            max_chars=3000,
        )
        brief = (context.input.get("brief") or "").strip()

        if not ctx.by_kind(ContextKind.REQUIREMENT).exists() and not brief:
            return AgentResult.failed(
                self.key,
                "No requirements found; run the Requirements Agent first "
                "(or pass a 'brief').",
            )

        existing = ctx.digest(
            kinds=[ContextKind.ARCHITECTURE, ContextKind.TECH_DECISION],
            max_chars=2000,
        )
        response = self.router.complete(
            RoutingRequest(complexity=TaskComplexity.HIGH, task_type="architecture"),
            messages=[
                Message("user", build_user_prompt(requirements_digest, existing, brief))
            ],
            system=SYSTEM_PROMPT,
            max_tokens=3000,
        )

        design = parse_architecture(response.text)
        source = f"agent:{self.key}#task:{context.metadata.get('task_id', '')}"

        for comp in design["components"]:
            ctx.set(
                ContextKind.ARCHITECTURE,
                slugify(comp["name"])[:255] or "component",
                title=comp["name"],
                content=comp["responsibility"],
                data={"technology": comp["technology"], "depends_on": comp["depends_on"]},
                source=source,
            )
        for dec in design["tech_decisions"]:
            ctx.set(
                ContextKind.TECH_DECISION,
                slugify(dec["title"])[:255] or "decision",
                title=dec["title"],
                content=dec["rationale"],
                data={"choice": dec["choice"]},
                source=source,
            )

        n_comp = len(design["components"])
        n_dec = len(design["tech_decisions"])
        if n_comp or n_dec:
            message = (
                f"Wrote {n_comp} component(s) and {n_dec} decision(s) via "
                f"{response.model}."
            )
        else:
            message = (
                f"{response.model} returned no parseable architecture; "
                "nothing was written."
            )
        return AgentResult.completed(
            self.key,
            output={
                "model": response.model,
                "components_written": n_comp,
                "decisions_written": n_dec,
            },
            messages=[message],
            model=response.model,
            usage_tokens=response.usage.total_tokens,
        )


register_runner(ArchitectAgent)
