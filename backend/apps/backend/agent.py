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
from apps.backend.prompts import build_user_prompt, repair_prompt, system_prompt
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

        system = system_prompt(stack)
        user_prompt = build_user_prompt(
            architecture, requirements, schema, existing_api, brief
        )

        # Generate, verify, and (on failure) repair before anything ships. We
        # verify in-memory first and only materialize code that we've either
        # confirmed compiles or exhausted repair attempts trying to fix.
        response = self._complete(system, [Message("user", user_prompt)])
        app_label = self._extract_app_label(stack, response.text)
        files = self._build_files(stack, response.text, app_label)
        verified, verify_log = (verify_python(files) if files else (None, ""))

        max_repairs = int(context.input.get("max_repairs", 2))
        total_tokens = response.usage.total_tokens
        final_response = response
        repair_rounds = 0

        while files and verified is False and repair_rounds < max_repairs:
            repair_rounds += 1
            fix = self._complete(
                system,
                [
                    Message("user", user_prompt),
                    Message("assistant", final_response.text),
                    Message("user", repair_prompt(stack, verify_log)),
                ],
            )
            total_tokens += fix.usage.total_tokens
            repaired = self._build_files(stack, fix.text, app_label)
            if not repaired:
                break  # model returned nothing usable; keep the prior attempt
            files, final_response = repaired, fix
            verified, verify_log = verify_python(files)

        source = f"agent:{self.key}#task:{context.metadata.get('task_id', '')}"
        endpoints = parse_backend(final_response.text)["endpoints"]
        self._persist_endpoints(ctx, endpoints, source)

        commit_sha = None
        if files:
            _, commit_sha = materialize(
                project,
                files,
                message=f"{stack.id} backend by {self.key} (task {context.metadata.get('task_id', '')})",
            )

        if not files:
            messages = [f"{final_response.model} returned no parseable code; nothing written."]
        else:
            check = "passed" if verified else "FAILED"
            note = f"[{stack.id}] generated {len(files)} file(s) via {final_response.model}."
            if repair_rounds:
                note += f" Self-repair rounds: {repair_rounds}."
            messages = [note, f"Compile check: {check} — {verify_log}"]

        return AgentResult.completed(
            self.key,
            output={
                "model": final_response.model,
                "stack": stack.id,
                "app_label": app_label,
                "endpoints_written": len(endpoints),
                "files_generated": len(files),
                "commit": commit_sha,
                "verified": verified,
                "repair_rounds": repair_rounds,
                "compile_log": verify_log,
            },
            messages=messages,
            model=final_response.model,
            usage_tokens=total_tokens,
        )

    def _complete(self, system, messages):
        return self.router.complete(
            RoutingRequest(complexity=TaskComplexity.HIGH, task_type="backend"),
            messages=messages,
            system=system,
            max_tokens=4000,
        )

    def _extract_app_label(self, stack, text):
        if not stack.needs_app_label:
            return None
        payload = extract_json(text) or {}
        return payload.get("app_label") if isinstance(payload, dict) else None

    def _build_files(self, stack, text, app_label):
        generated = parse_files(text)
        return stack.build_project(app_label, generated) if generated else []

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
