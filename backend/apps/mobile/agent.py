"""Mobile Agent — designs the mobile app for the project's chosen framework.

Stack-aware: reads `technology.mobile` (e.g. Flutter, SwiftUI) and designs screens
tailored to it, persisted as SCREEN context entries marked platform="mobile".
Design-only for now — mobile toolchains (Dart/Swift) aren't available in the build
sandbox, so it does not claim to compile or run anything.
"""
from __future__ import annotations

from django.utils.text import slugify

from apps.agents.base import AgentContext, AgentResult, BaseAgent
from apps.agents.capabilities import Capability
from apps.agents.definitions import MOBILE
from apps.agents.runners import register_runner
from apps.ai_providers.base import Message
from apps.frontend.parsing import parse_frontend
from apps.model_router.router import ModelRouter, RoutingRequest, TaskComplexity
from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.projects.models import Project
from apps.technology.registry import technology_for_role

SYSTEM_PROMPT = (
    "You are the Mobile Agent for DevForge. Given a project's requirements and "
    "API, design the screens of the mobile app for the chosen mobile framework.\n\n"
    "Respond with ONLY a JSON object with one key:\n"
    '  "screens": array of objects with "name", "purpose", "route", '
    '"components" (array of UI element names), and "data_needs" (array of API '
    "endpoints this screen consumes).\n"
    "Cover the core mobile user journeys. No prose outside the JSON."
)


def _build_prompt(framework, requirements, api, existing, brief):
    parts = []
    if framework:
        parts.append(f"Target mobile framework: {framework}.")
    if brief.strip():
        parts.append("Product brief:\n" + brief.strip())
    if requirements.strip():
        parts.append("Requirements:\n" + requirements.strip())
    if api.strip():
        parts.append("Available API:\n" + api.strip())
    if existing.strip():
        parts.append("Existing mobile screens (refine, don't duplicate):\n" + existing.strip())
    parts.append("Return the JSON mobile screen design.")
    return "\n\n".join(parts)


class MobileAgent(BaseAgent):
    key = MOBILE.key
    name = MOBILE.name
    description = MOBILE.description
    capabilities = MOBILE.capabilities

    def __init__(self, router: ModelRouter | None = None):
        self.router = router or ModelRouter()

    def execute(self, context: AgentContext) -> AgentResult:
        self.require(Capability.WRITE_FRONTEND)

        if not context.project_id:
            return AgentResult.failed(self.key, "Mobile work needs a project.")

        project = Project.objects.get(id=context.project_id)
        ctx = ProjectContext(project)
        brief = (context.input.get("brief") or "").strip()

        if not ctx.by_kind(ContextKind.REQUIREMENT).exists() and not brief:
            return AgentResult.failed(
                self.key,
                "No requirements found; run the Requirements Agent first "
                "(or pass a 'brief').",
            )

        framework = technology_for_role(project, "mobile")
        fw_name = framework.name if framework else ""
        requirements = ctx.digest(kinds=[ContextKind.REQUIREMENT], max_chars=2500)
        api = ctx.digest(kinds=[ContextKind.API], max_chars=2000)
        # Only this agent's own (mobile) screens, to avoid clashing with web screens.
        existing = "\n".join(
            e.title
            for e in ctx.by_kind(ContextKind.SCREEN)
            if (e.data or {}).get("platform") == "mobile"
        )

        response = self.router.complete(
            RoutingRequest(complexity=TaskComplexity.MEDIUM, task_type="mobile"),
            messages=[Message("user", _build_prompt(fw_name, requirements, api, existing, brief))],
            system=SYSTEM_PROMPT,
            max_tokens=3000,
        )

        screens = parse_frontend(response.text)["screens"]
        source = f"agent:{self.key}#task:{context.metadata.get('task_id', '')}"
        for screen in screens:
            ctx.set(
                ContextKind.SCREEN,
                slugify(f"mobile {screen['name']}")[:255] or "mobile-screen",
                title=f"[mobile] {screen['name']}",
                content=screen["purpose"],
                data={
                    "route": screen["route"],
                    "components": screen["components"],
                    "data_needs": screen["data_needs"],
                    "framework": framework.id if framework else None,
                    "platform": "mobile",
                },
                source=source,
            )

        n = len(screens)
        fw_label = fw_name or "unspecified framework"
        message = (
            f"Designed {n} mobile screen(s) for {fw_label} via {response.model}."
            if n
            else f"{response.model} returned no parseable screens; nothing written."
        )
        return AgentResult.completed(
            self.key,
            output={
                "model": response.model,
                "screens_written": n,
                "mobile_stack": framework.id if framework else None,
            },
            messages=[message],
            model=response.model,
            usage_tokens=response.usage.total_tokens,
        )


register_runner(MobileAgent)
