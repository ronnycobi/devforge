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
from apps.backend.prompts import (
    build_user_prompt,
    repair_prompt,
    system_prompt,
    test_repair_prompt,
)
from apps.codegen.parsing import parse_files
from apps.codegen.service import materialize, run_repo_tests, verify_python
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
        max_repairs = int(context.input.get("max_repairs", 2))
        run_tests = context.input.get("run_tests", True)

        # Generate, then verify and repair before anything is declared done.
        # A single repair budget covers two kinds of failure, in order:
        #   1. compile — checked in-memory (cheap), repaired before we materialize;
        #   2. tests   — real suite run in the sandbox once it compiles, repaired
        #                against the actual failure output.
        response = self._complete(system, [Message("user", user_prompt)])
        app_label = self._extract_app_label(stack, response.text)
        files = self._build_files(stack, response.text, app_label)
        final_response = response
        total_tokens = response.usage.total_tokens
        rounds = 0

        # Phase 1: compile.
        compiled, compile_log = (verify_python(files) if files else (None, ""))
        while files and compiled is False and rounds < max_repairs:
            rounds += 1
            fix, repaired = self._ask_repair(
                stack, system, user_prompt, final_response.text,
                repair_prompt(stack, compile_log), app_label,
            )
            total_tokens += fix.usage.total_tokens
            if not repaired:
                break  # nothing usable came back; keep the prior attempt
            files, final_response = repaired, fix
            compiled, compile_log = verify_python(files)

        commit_sha = self._materialize(project, stack, files, context) if files else None

        # Phase 2: real tests (only if it compiles and the caller wants them).
        tests_passed, test_log, tests_ran = None, "", 0
        if files and compiled and run_tests:
            result = run_repo_tests(project)
            tests_passed = result.get("passed")
            tests_ran = result.get("ran", 0)
            test_log = (result.get("output") or result.get("note") or "").strip()
            while tests_passed is False and rounds < max_repairs:
                rounds += 1
                fix, repaired = self._ask_repair(
                    stack, system, user_prompt, final_response.text,
                    test_repair_prompt(stack, test_log), app_label,
                )
                total_tokens += fix.usage.total_tokens
                if not repaired:
                    break
                files, final_response = repaired, fix
                compiled, compile_log = verify_python(files)
                commit_sha = self._materialize(project, stack, files, context)
                if not compiled:
                    break  # the fix broke compilation; reported honestly below
                result = run_repo_tests(project)
                tests_passed = result.get("passed")
                tests_ran = result.get("ran", 0)
                test_log = (result.get("output") or result.get("note") or "").strip()

        source = f"agent:{self.key}#task:{context.metadata.get('task_id', '')}"
        endpoints = parse_backend(final_response.text)["endpoints"]
        self._persist_endpoints(ctx, endpoints, source)

        messages = self._summary(stack, final_response, files, rounds, compiled,
                                  compile_log, run_tests, tests_passed, tests_ran, test_log)

        return AgentResult.completed(
            self.key,
            output={
                "model": final_response.model,
                "stack": stack.id,
                "app_label": app_label,
                "endpoints_written": len(endpoints),
                "files_generated": len(files),
                "commit": commit_sha,
                "verified": compiled,
                "tests_passed": tests_passed,
                "tests_ran": tests_ran,
                "repair_rounds": rounds,
                "compile_log": compile_log,
                "test_log": test_log[-2000:],
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

    def _ask_repair(self, stack, system, user_prompt, prior_text, instruction, app_label):
        """One repair turn: show the model its prior answer + the failure, rebuild."""
        fix = self._complete(system, [
            Message("user", user_prompt),
            Message("assistant", prior_text),
            Message("user", instruction),
        ])
        return fix, self._build_files(stack, fix.text, app_label)

    def _materialize(self, project, stack, files, context):
        _, sha = materialize(
            project, files,
            message=f"{stack.id} backend by {self.key} (task {context.metadata.get('task_id', '')})",
        )
        return sha

    @staticmethod
    def _summary(stack, response, files, rounds, compiled, compile_log,
                 run_tests, tests_passed, tests_ran, test_log):
        if not files:
            return [f"{response.model} returned no parseable code; nothing written."]
        note = f"[{stack.id}] generated {len(files)} file(s) via {response.model}."
        if rounds:
            note += f" Self-repair rounds: {rounds}."
        out = [note, f"Compile check: {'passed' if compiled else 'FAILED'} — {compile_log}"]
        if run_tests and compiled:
            if tests_passed is True:
                out.append(f"Tests: passed ({tests_ran} run).")
            elif tests_passed is False:
                out.append(f"Tests: FAILED — {test_log[-300:]}")
            else:
                out.append(f"Tests: not run — {test_log or 'nothing runnable here'}.")
        return out

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
