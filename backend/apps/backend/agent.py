"""Backend Agent — implements the backend in the project's chosen stack.

The stack comes from (in order) task input `stack`, the project's technology
profile (`technology.backend`), or the default `python-stdlib`. DevForge is
stack-agnostic: the agent resolves a Stack runner (technology.stacks) and uses its
scaffolder + guidance, so Django, a stdlib project, or any future stack all flow
through the same code. A requested stack that DevForge can't yet generate fails
honestly (it names the blocker) rather than silently generating the wrong thing.

It persists the API design (pipeline intact), writes files into the project git
repo, commits, and compile-checks generated Python. Offline generates nothing;
compile failures are reported, not hidden.
"""
from __future__ import annotations

from django.utils.text import slugify

from apps.agents.base import AgentContext, AgentResult, BaseAgent
from apps.agents.capabilities import Capability
from apps.agents.definitions import BACKEND
from apps.agents.runners import register_runner
from apps.ai_providers.base import Message
from apps.backend.parsing import parse_backend
from apps.backend.prompts import build_user_prompt, system_prompt
from apps.codegen.parsing import parse_files
from apps.codegen.service import materialize, verify_python
from apps.core.jsonx import extract_json
from apps.model_router.router import ModelRouter, RoutingRequest, TaskComplexity
from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.projects.models import Project
from apps.technology.registry import registry as tech_registry
from apps.technology.stacks import get_stack

DEFAULT_BACKEND_STACK = "python-stdlib"


class BackendAgent(BaseAgent):
    key = BACKEND.key
    name = BACKEND.name
    description = BACKEND.description
    capabilities = BACKEND.capabilities

    def __init__(self, router: ModelRouter | None = None):
        self.router = router or ModelRouter()

    def _resolve_stack(self, project, context):
        stack_id = (
            context.input.get("stack")
            or (project.technology or {}).get("backend")
            or DEFAULT_BACKEND_STACK
        )
        stack = get_stack(stack_id)
        if stack is not None:
            return stack, None
        # Known ecosystem but no code-gen yet vs. entirely unknown — either way, be honest.
        tech = tech_registry.get(stack_id)
        if tech is not None:
            return None, (
                f"Stack '{stack_id}' ({tech.name}) is a known technology but "
                "DevForge cannot generate it yet (generation planned)."
            )
        return None, f"Unknown stack '{stack_id}'."

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

        stack, blocker = self._resolve_stack(project, context)
        if stack is None:
            return AgentResult.failed(self.key, blocker)

        architecture = ctx.digest(
            kinds=[ContextKind.ARCHITECTURE, ContextKind.TECH_DECISION], max_chars=2500
        )
        requirements = ctx.digest(kinds=[ContextKind.REQUIREMENT], max_chars=2000)
        schema = ctx.digest(kinds=[ContextKind.SCHEMA], max_chars=2000)
        existing_api = ctx.digest(kinds=[ContextKind.API], max_chars=1000)

        response = self.router.complete(
            RoutingRequest(complexity=TaskComplexity.HIGH, task_type="backend"),
            messages=[
                Message(
                    "user",
                    build_user_prompt(architecture, requirements, schema, existing_api, brief),
                )
            ],
            system=system_prompt(stack),
            max_tokens=4000,
        )

        source = f"agent:{self.key}#task:{context.metadata.get('task_id', '')}"
        endpoints = parse_backend(response.text)["endpoints"]
        self._persist_endpoints(ctx, endpoints, source)

        generated = parse_files(response.text)
        app_label = None
        if stack.needs_app_label:
            payload = extract_json(response.text) or {}
            app_label = payload.get("app_label") if isinstance(payload, dict) else None
        files = stack.build_project(app_label, generated) if generated else []

        commit_sha, verified, verify_log = None, None, ""
        if files:
            _, commit_sha = materialize(
                project,
                files,
                message=f"{stack.id} backend by {self.key} (task {context.metadata.get('task_id', '')})",
            )
            verified, verify_log = verify_python(files)

        messages = [f"[{stack.id}] generated {len(files)} file(s) via {response.model}."]
        if files:
            messages.append(
                f"Compile check: {'passed' if verified else 'FAILED'} — {verify_log}"
            )
        else:
            messages = [f"{response.model} returned no parseable code; nothing written."]

        return AgentResult.completed(
            self.key,
            output={
                "model": response.model,
                "stack": stack.id,
                "app_label": app_label,
                "endpoints_written": len(endpoints),
                "files_generated": len(files),
                "commit": commit_sha,
                "verified": verified,
                "compile_log": verify_log,
            },
            messages=messages,
            model=response.model,
            usage_tokens=response.usage.total_tokens,
        )

    def _persist_endpoints(self, ctx, endpoints, source):
        for ep in endpoints:
            key = slugify(f"{ep['method']} {ep['path'].replace('/', ' ')}")[:255] or "endpoint"
            ctx.set(
                ContextKind.API,
                key,
                title=f"{ep['method']} {ep['path']}",
                content=ep["purpose"],
                data={k: ep[k] for k in ("method", "path", "module", "auth", "request", "response")},
                source=source,
            )


register_runner(BackendAgent)
