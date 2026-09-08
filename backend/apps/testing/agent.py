"""Testing Agent — designs the test plan from requirements + API.

Persists each test case as a TESTING context entry (keyed by title, upsert).
Declares/enforces read-backend/frontend/tests + write-tests + run-tests. Executing
the tests against generated code belongs to the build phase; this designs the plan
those runs will follow.
"""
from __future__ import annotations

from django.utils.text import slugify

from apps.agents.base import AgentContext, AgentResult, BaseAgent
from apps.agents.capabilities import Capability
from apps.agents.definitions import TESTING
from apps.agents.runners import register_runner
from apps.ai_providers.base import Message
from apps.tools.registry import Toolbelt
from apps.model_router.router import ModelRouter, RoutingRequest, TaskComplexity
from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.projects.models import Project
from apps.testing.parsing import parse_tests
from apps.testing.prompts import SYSTEM_PROMPT, build_user_prompt


class TestingAgent(BaseAgent):
    key = TESTING.key
    name = TESTING.name
    description = TESTING.description
    capabilities = TESTING.capabilities

    def __init__(self, router: ModelRouter | None = None):
        self.router = router or ModelRouter()

    def execute(self, context: AgentContext) -> AgentResult:
        self.require(Capability.WRITE_TESTS)

        if not context.project_id:
            return AgentResult.failed(self.key, "Test work needs a project.")

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
        existing = ctx.digest(kinds=[ContextKind.TESTING], max_chars=1500)

        response = self.router.complete(
            RoutingRequest(complexity=TaskComplexity.MEDIUM, task_type="testing"),
            messages=[Message("user", build_user_prompt(requirements, api, existing, brief))],
            system=SYSTEM_PROMPT,
            max_tokens=3000,
        )

        cases = parse_tests(response.text)["test_cases"]
        source = f"agent:{self.key}#task:{context.metadata.get('task_id', '')}"
        for case in cases:
            ctx.set(
                ContextKind.TESTING,
                slugify(case["title"])[:255] or "test",
                title=case["title"],
                content=case["expected"],
                data={
                    "kind": case["kind"],
                    "target": case["target"],
                    "steps": case["steps"],
                },
                source=source,
            )

        n = len(cases)
        messages = [
            f"Designed {n} test case(s) via {response.model}."
            if n
            else f"{response.model} returned no parseable tests."
        ]

        # Run the generated project's test suite via the tests.run tool, so it is
        # governed by this agent's RUN_TESTS capability like any other tool use.
        test_run = Toolbelt(project, self.capabilities).invoke("tests.run", "run").data or {}
        if test_run.get("passed") is None:
            messages.append(f"No runnable tests in repo ({test_run.get('note')}).")
        else:
            verdict = "PASSED" if test_run["passed"] else "FAILED"
            messages.append(
                f"Ran {test_run['ran']} repo test(s): {verdict} "
                f"(failures={test_run['failures']}, errors={test_run['errors']})."
            )

        return AgentResult.completed(
            self.key,
            output={
                "model": response.model,
                "tests_written": n,
                "test_run": test_run,
            },
            messages=messages,
            model=response.model,
            usage_tokens=response.usage.total_tokens,
        )


register_runner(TestingAgent)
