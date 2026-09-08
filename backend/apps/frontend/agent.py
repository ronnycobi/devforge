"""Frontend Agent — designs the app screens AND generates runnable source.

Always persists screens as SCREEN context entries (keyed by name, upsert). When
the project's frontend technology maps to a runnable frontend Stack (e.g. React),
it also generates real source and runs it through the shared verify → repair loop
(codegen.repair): the framework app is committed for export, and its framework-
free logic layer is unit-tested here with `node --test`. Frameworks DevForge
can't run yet (no toolchain) stay design-only — recorded, honestly not faked.

Declares/enforces only read-architecture + read/write-frontend + run-tests — it
cannot touch backend or billing.
"""
from __future__ import annotations

from django.utils.text import slugify

from apps.agents.base import AgentContext, AgentResult, BaseAgent
from apps.agents.capabilities import Capability
from apps.agents.definitions import FRONTEND
from apps.agents.runners import register_runner
from apps.ai_providers.base import Message
from apps.codegen.parsing import parse_files
from apps.codegen.repair import verify_and_repair
from apps.tools.registry import Toolbelt
from apps.frontend.parsing import parse_frontend
from apps.frontend.prompts import build_user_prompt, system_prompt
from apps.model_router.router import ModelRouter, RoutingRequest, TaskComplexity
from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.projects.models import Project
from apps.technology.registry import technology_for_role
from apps.technology.stacks import get_stack

# Default runnable frontend when the project chose a framework we can generate.
DEFAULT_FRONTEND_STACK = "react"


class FrontendAgent(BaseAgent):
    key = FRONTEND.key
    name = FRONTEND.name
    description = FRONTEND.description
    capabilities = FRONTEND.capabilities

    def __init__(self, router: ModelRouter | None = None):
        self.router = router or ModelRouter()

    def _resolve_stack(self, project, context):
        """A runnable frontend Stack, or None to stay design-only."""
        stack_id = context.input.get("stack")
        if not stack_id:
            framework = technology_for_role(project, "frontend")
            stack_id = framework.id if framework else DEFAULT_FRONTEND_STACK
        stack = get_stack(stack_id)
        return stack if (stack and stack.kind == "frontend") else None

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
        stack = self._resolve_stack(project, context)
        tid = context.metadata.get("task_id", "")

        system = system_prompt(stack)
        user_prompt = build_user_prompt(requirements, api, existing, brief, framework=fw_name)
        response = self._complete(system, [Message("user", user_prompt)])

        # Generate + verify runnable source through the shared loop (when the
        # chosen framework is one DevForge can run). Otherwise stay design-only.
        outcome = None
        if stack is not None:
            outcome = verify_and_repair(
                toolbelt=Toolbelt(project, self.capabilities),
                complete=lambda messages: self._complete(system, messages),
                initial_response=response,
                user_prompt=user_prompt,
                build_files=lambda text: self._build_files(stack, text),
                materialize_message=f"{stack.id} frontend by {self.key} (task {tid})",
                max_repairs=int(context.input.get("max_repairs", 2)),
                run_tests=context.input.get("run_tests", True),
            )

        final_text = outcome.final_text if outcome else response.text
        model = outcome.model if outcome else response.model
        tokens = outcome.total_tokens if outcome else response.usage.total_tokens

        screens = parse_frontend(final_text)["screens"]
        source = f"agent:{self.key}#task:{tid}"
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

        return AgentResult.completed(
            self.key,
            output=self._output(framework, stack, screens, outcome, model),
            messages=self._summary(fw_name, screens, stack, outcome, model),
            model=model,
            usage_tokens=tokens,
        )

    def _complete(self, system, messages):
        return self.router.complete(
            RoutingRequest(complexity=TaskComplexity.MEDIUM, task_type="frontend"),
            messages=messages,
            system=system,
            max_tokens=3000,
        )

    @staticmethod
    def _build_files(stack, text):
        # Only scaffold when the model actually produced source — offline (stub)
        # returns nothing, so nothing is generated (honest no-op).
        files = parse_files(text)
        return stack.build_project(None, files) if files else []

    @staticmethod
    def _output(framework, stack, screens, outcome, model):
        out = {
            "model": model,
            "screens_written": len(screens),
            "frontend_stack": (stack.id if stack else (framework.id if framework else None)),
            "code_generated": bool(outcome and outcome.files),
            "files_generated": len(outcome.files) if outcome else 0,
        }
        if outcome:
            out.update({
                "commit": outcome.commit_sha,
                "verified": outcome.compiled,
                "tests_passed": outcome.tests_passed,
                "tests_ran": outcome.tests_ran,
                "repair_rounds": outcome.repair_rounds,
                "test_log": outcome.test_log[-2000:],
            })
        return out

    @staticmethod
    def _summary(fw_name, screens, stack, outcome, model):
        n = len(screens)
        fw_label = fw_name or (stack.framework if stack else None) or "unspecified framework"
        if not n and not (outcome and outcome.files):
            return [f"{model} returned nothing parseable; nothing written."]
        msgs = [f"Designed {n} screen(s) for {fw_label} via {model}."]
        if outcome and outcome.files:
            msgs.append(f"Generated {len(outcome.files)} source file(s) for {stack.id}.")
            if outcome.tests_passed is True:
                msgs.append(f"Logic tests: passed ({outcome.tests_ran} run)"
                            + (f" after {outcome.repair_rounds} repair round(s)" if outcome.repair_rounds else "") + ".")
            elif outcome.tests_passed is False:
                msgs.append(f"Logic tests: FAILED — {outcome.test_log[-300:]}")
            else:
                msgs.append("Logic tests: not run — no runnable toolchain here.")
        return msgs


register_runner(FrontendAgent)
