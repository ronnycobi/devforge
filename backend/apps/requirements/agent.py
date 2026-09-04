"""Requirements Agent — the first shipped executable specialist.

Given a product brief on the task input, it asks a model (via the Model Router,
so provider/model selection and failover are handled) for structured functional
requirements, then persists each as a ContextEntry in project memory. It reads
the existing requirements digest first so it stays consistent and doesn't
duplicate. It declares — and enforces — only WRITE_REQUIREMENTS/READ_REQUIREMENTS.

Offline (stub provider) the model returns nothing parseable, so the agent
completes with 0 requirements and says so — an honest no-op, never a fabricated
requirement. With ANTHROPIC_API_KEY set it produces real requirements.
"""
from __future__ import annotations

from apps.agents.base import AgentContext, AgentResult, BaseAgent
from apps.agents.capabilities import Capability
from apps.agents.definitions import REQUIREMENTS
from apps.agents.runners import register_runner
from apps.ai_providers.base import Message
from apps.model_router.router import ModelRouter, RoutingRequest, TaskComplexity
from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.projects.models import Project
from apps.requirements.parsing import parse_requirements
from apps.requirements.prompts import SYSTEM_PROMPT, build_user_prompt


class RequirementsAgent(BaseAgent):
    # Metadata and permissions come straight from the catalog entry, so declared
    # capabilities and enforced capabilities are the same set.
    key = REQUIREMENTS.key
    name = REQUIREMENTS.name
    description = REQUIREMENTS.description
    capabilities = REQUIREMENTS.capabilities

    def __init__(self, router: ModelRouter | None = None):
        self.router = router or ModelRouter()

    def execute(self, context: AgentContext) -> AgentResult:
        self.require(Capability.WRITE_REQUIREMENTS)

        brief = (
            context.input.get("brief") or context.input.get("description") or ""
        ).strip()
        if not brief:
            return AgentResult.failed(
                self.key, "No 'brief' or 'description' provided in task input."
            )
        if not context.project_id:
            return AgentResult.failed(self.key, "Requirements work needs a project.")

        project = Project.objects.get(id=context.project_id)
        ctx = ProjectContext(project)
        existing = ctx.digest(
            kinds=[ContextKind.REQUIREMENT, ContextKind.BUSINESS_RULE],
            max_chars=2000,
        )

        response = self.router.complete(
            RoutingRequest(
                complexity=TaskComplexity.MEDIUM, task_type="requirements"
            ),
            messages=[Message("user", build_user_prompt(brief, existing))],
            system=SYSTEM_PROMPT,
            max_tokens=2000,
        )

        requirements = parse_requirements(response.text)
        source = f"agent:{self.key}#task:{context.metadata.get('task_id', '')}"
        created_ids = []
        for req in requirements:
            entry = ctx.add(
                ContextKind.REQUIREMENT,
                title=req["title"],
                content=req["description"],
                data={"acceptance_criteria": req["acceptance_criteria"]},
                source=source,
            )
            created_ids.append(entry.id)

        if created_ids:
            message = f"Extracted {len(created_ids)} requirement(s) via {response.model}."
        else:
            message = (
                f"{response.model} returned no parseable requirements; "
                "nothing was written."
            )
        return AgentResult.completed(
            self.key,
            output={
                "model": response.model,
                "requirements_created": len(created_ids),
                "requirement_ids": created_ids,
            },
            messages=[message],
            model=response.model,
            usage_tokens=response.usage.total_tokens,
        )


register_runner(RequirementsAgent)
