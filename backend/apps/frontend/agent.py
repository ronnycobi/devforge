"""Frontend Agent — designs the app screens from requirements + API.

Persists screens as SCREEN context entries (keyed by name, upsert). Declares/
enforces only read-architecture + read/write-frontend + run-tests — it cannot
touch backend or billing. Actual Flutter source generation lands with the
artifact/build/export phases; this produces the screen design that will drive it.
"""
from __future__ import annotations

from django.utils.text import slugify

from apps.agents.base import AgentContext, AgentResult, BaseAgent
from apps.agents.capabilities import Capability
from apps.agents.definitions import FRONTEND
from apps.agents.runners import register_runner
from apps.ai_providers.base import Message
from apps.frontend.parsing import parse_frontend
from apps.frontend.prompts import SYSTEM_PROMPT, build_user_prompt
from apps.model_router.router import ModelRouter, RoutingRequest, TaskComplexity
from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.projects.models import Project
from apps.technology.registry import technology_for_role


class FrontendAgent(BaseAgent):
    key = FRONTEND.key
    name = FRONTEND.name
    description = FRONTEND.description
    capabilities = FRONTEND.capabilities

    def __init__(self, router: ModelRouter | None = None):
        self.router = router or ModelRouter()

    def execute(self, context: AgentContext) -> AgentResult:
        self.require(Capability.WRITE_FRONTEND)

        if not context.project_id:
            return AgentResult.failed(self.key, "Frontend work needs a project.")

        project = Project.objects.get(id=context.project_id)
        ctx = ProjectContext(project)
        brief = (context.input.get("brief") or "").strip()

        if not ctx.by_kind(ContextKind.REQUIREMENT).exists() and not brief:
            return AgentResult.failed(
                self.key,
                "No requirements found; run the Requirements Agent first "
                "(or pass a 'brief').",
            )

        requirements = ctx.digest(kinds=[ContextKind.REQUIREMENT], max_chars=2500)
        api = ctx.digest(kinds=[ContextKind.API], max_chars=2000)
        existing = ctx.digest(kinds=[ContextKind.SCREEN], max_chars=1500)

        framework = technology_for_role(project, "frontend")
        fw_name = framework.name if framework else ""

        response = self.router.complete(
            RoutingRequest(complexity=TaskComplexity.MEDIUM, task_type="frontend"),
            messages=[
                Message(
                    "user",
                    build_user_prompt(requirements, api, existing, brief, framework=fw_name),
                )
            ],
            system=SYSTEM_PROMPT,
            max_tokens=3000,
        )

        screens = parse_frontend(response.text)["screens"]
        source = f"agent:{self.key}#task:{context.metadata.get('task_id', '')}"
        for screen in screens:
            ctx.set(
                ContextKind.SCREEN,
                slugify(screen["name"])[:255] or "screen",
                title=screen["name"],
                content=screen["purpose"],
                data={
                    "route": screen["route"],
                    "components": screen["components"],
                    "data_needs": screen["data_needs"],
                    "framework": framework.id if framework else None,
                    "platform": "web",
                },
                source=source,
            )

        n = len(screens)
        fw_label = fw_name or "unspecified framework"
        message = (
            f"Designed {n} screen(s) for {fw_label} via {response.model}."
            if n
            else f"{response.model} returned no parseable screens; nothing written."
        )
        return AgentResult.completed(
            self.key,
            output={
                "model": response.model,
                "screens_written": n,
                "frontend_stack": framework.id if framework else None,
            },
            messages=[message],
            model=response.model,
            usage_tokens=response.usage.total_tokens,
        )


register_runner(FrontendAgent)
