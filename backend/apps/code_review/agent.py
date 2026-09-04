"""Code Review Agent — reviews the project design for issues.

Until generated code exists (build/export phases), it reviews the accumulated
design context — requirements, architecture, API, schema — for gaps,
inconsistencies, and security concerns, and records findings as REVIEW entries.
Declares/enforces read-backend/frontend/tests + review-code only; it never
modifies anything but its own findings.
"""
from __future__ import annotations

from django.utils.text import slugify

from apps.agents.base import AgentContext, AgentResult, BaseAgent
from apps.agents.capabilities import Capability
from apps.agents.definitions import CODE_REVIEW
from apps.agents.runners import register_runner
from apps.ai_providers.base import Message
from apps.code_review.parsing import parse_findings
from apps.code_review.prompts import SYSTEM_PROMPT, build_user_prompt
from apps.model_router.router import ModelRouter, RoutingRequest, TaskComplexity
from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.projects.models import Project

_REVIEWABLE = [
    ContextKind.REQUIREMENT,
    ContextKind.ARCHITECTURE,
    ContextKind.TECH_DECISION,
    ContextKind.API,
    ContextKind.SCHEMA,
    ContextKind.SCREEN,
]


class CodeReviewAgent(BaseAgent):
    key = CODE_REVIEW.key
    name = CODE_REVIEW.name
    description = CODE_REVIEW.description
    capabilities = CODE_REVIEW.capabilities

    def __init__(self, router: ModelRouter | None = None):
        self.router = router or ModelRouter()

    def execute(self, context: AgentContext) -> AgentResult:
        self.require(Capability.REVIEW_CODE)

        if not context.project_id:
            return AgentResult.failed(self.key, "Review work needs a project.")

        project = Project.objects.get(id=context.project_id)
        ctx = ProjectContext(project)

        if not ctx.all().filter(kind__in=_REVIEWABLE).exists():
            return AgentResult.failed(
                self.key, "Nothing to review; the project has no design yet."
            )

        design = ctx.digest(kinds=_REVIEWABLE, max_chars=6000)
        response = self.router.complete(
            RoutingRequest(complexity=TaskComplexity.HIGH, task_type="code_review"),
            messages=[Message("user", build_user_prompt(design))],
            system=SYSTEM_PROMPT,
            max_tokens=3000,
        )

        findings = parse_findings(response.text)["findings"]
        source = f"agent:{self.key}#task:{context.metadata.get('task_id', '')}"
        for finding in findings:
            ctx.set(
                ContextKind.REVIEW,
                slugify(finding["title"])[:255] or "finding",
                title=finding["title"],
                content=finding["recommendation"],
                data={"severity": finding["severity"], "area": finding["area"]},
                source=source,
            )

        n = len(findings)
        message = (
            f"Recorded {n} review finding(s) via {response.model}."
            if n
            else f"{response.model} reported no findings (or none parseable)."
        )
        return AgentResult.completed(
            self.key,
            output={"model": response.model, "findings_written": n},
            messages=[message],
            model=response.model,
            usage_tokens=response.usage.total_tokens,
        )


register_runner(CodeReviewAgent)
