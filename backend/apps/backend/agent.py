"""Backend Agent — designs the backend HTTP API against the architecture.

Reads the architecture and requirements from context and produces API endpoints,
persisted as API context entries (keyed by method+path, so re-running refines in
place). This is the "backend and APIs" design; generating and storing the actual
backend source is wired once the artifact/build/export phases exist (16/18) —
until then the agent produces the API design the code generation will implement,
never code it cannot store or run.
"""
from __future__ import annotations

from django.utils.text import slugify

from apps.agents.base import AgentContext, AgentResult, BaseAgent
from apps.agents.capabilities import Capability
from apps.agents.definitions import BACKEND
from apps.agents.runners import register_runner
from apps.ai_providers.base import Message
from apps.backend.parsing import parse_backend
from apps.backend.prompts import SYSTEM_PROMPT, build_user_prompt
from apps.model_router.router import ModelRouter, RoutingRequest, TaskComplexity
from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.projects.models import Project


class BackendAgent(BaseAgent):
    key = BACKEND.key
    name = BACKEND.name
    description = BACKEND.description
    capabilities = BACKEND.capabilities

    def __init__(self, router: ModelRouter | None = None):
        self.router = router or ModelRouter()

    def execute(self, context: AgentContext) -> AgentResult:
        self.require(Capability.WRITE_BACKEND)

        if not context.project_id:
            return AgentResult.failed(self.key, "Backend work needs a project.")

        project = Project.objects.get(id=context.project_id)
        ctx = ProjectContext(project)
        brief = (context.input.get("brief") or "").strip()

        if not ctx.by_kind(ContextKind.ARCHITECTURE).exists() and not brief:
            return AgentResult.failed(
                self.key,
                "No architecture found; run the Architect Agent first "
                "(or pass a 'brief').",
            )

        architecture = ctx.digest(
            kinds=[ContextKind.ARCHITECTURE, ContextKind.TECH_DECISION], max_chars=3000
        )
        requirements = ctx.digest(kinds=[ContextKind.REQUIREMENT], max_chars=2000)
        existing_api = ctx.digest(kinds=[ContextKind.API], max_chars=1500)

        response = self.router.complete(
            RoutingRequest(complexity=TaskComplexity.HIGH, task_type="backend"),
            messages=[
                Message(
                    "user",
                    build_user_prompt(architecture, requirements, existing_api, brief),
                )
            ],
            system=SYSTEM_PROMPT,
            max_tokens=3000,
        )

        endpoints = parse_backend(response.text)["endpoints"]
        source = f"agent:{self.key}#task:{context.metadata.get('task_id', '')}"
        for ep in endpoints:
            key = slugify(f"{ep['method']} {ep['path'].replace('/', ' ')}")[:255] or "endpoint"
            ctx.set(
                ContextKind.API,
                key,
                title=f"{ep['method']} {ep['path']}",
                content=ep["purpose"],
                data={
                    "method": ep["method"],
                    "path": ep["path"],
                    "module": ep["module"],
                    "auth": ep["auth"],
                    "request": ep["request"],
                    "response": ep["response"],
                },
                source=source,
            )

        n = len(endpoints)
        message = (
            f"Designed {n} endpoint(s) via {response.model}."
            if n
            else f"{response.model} returned no parseable endpoints; nothing written."
        )
        return AgentResult.completed(
            self.key,
            output={"model": response.model, "endpoints_written": n},
            messages=[message],
            model=response.model,
            usage_tokens=response.usage.total_tokens,
        )


register_runner(BackendAgent)
