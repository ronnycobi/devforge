"""Security Agent — deterministic static security scan of the project's code.

Reads the project repo and runs the offline scanner (secrets, injection sinks,
unsafe deserialization, framework foot-guns), recording findings in the twin as
SECURITY entries and returning a severity summary. It always completes (the scan
ran); the findings — including how many are HIGH/blocking — are the output, so
they surface on the change and in project intelligence. No model, no cost.
"""
from __future__ import annotations

from django.utils.text import slugify

from apps.agents.base import AgentContext, AgentResult, BaseAgent
from apps.agents.capabilities import Capability
from apps.agents.definitions import SECURITY
from apps.agents.runners import register_runner
from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.projects.models import Project
from apps.security.scanner import scan_files, summarize
from apps.tools.registry import Toolbelt


class SecurityAgent(BaseAgent):
    key = SECURITY.key
    name = SECURITY.name
    description = SECURITY.description
    capabilities = SECURITY.capabilities

    def execute(self, context: AgentContext) -> AgentResult:
        self.require(Capability.REVIEW_CODE)

        if not context.project_id:
            return AgentResult.failed(self.key, "Security scan needs a project.")

        project = Project.objects.get(id=context.project_id)
        # Read the code through the Tool Registry — the Toolbelt enforces that this
        # agent holds USE_REPOSITORY before the repo.read tool will run.
        belt = Toolbelt(project, self.capabilities)
        result = belt.invoke("repo.read", "read_all")
        files: dict[str, str] = result.data if result.ok else {}

        findings = scan_files(files)
        summary = summarize(findings)

        ctx = ProjectContext(project)
        source = f"agent:{self.key}#task:{context.metadata.get('task_id', '')}"
        for i, f in enumerate(findings[:50]):
            key = slugify(f"{f.category}-{f.path}-{f.line}")[:255] or f"finding-{i}"
            ctx.set(
                ContextKind.SECURITY, key,
                title=f"[{f.severity}] {f.message}",
                content=f"{f.path}:{f.line} — {f.evidence}",
                data=f.as_dict(), source=source,
            )

        if not files:
            message = "No code to scan yet."
        elif summary["total"] == 0:
            message = f"Scanned {len(files)} file(s): no security findings."
        else:
            message = (
                f"Scanned {len(files)} file(s): {summary['high']} high, "
                f"{summary['medium']} medium, {summary['low']} low."
            )

        return AgentResult.completed(
            self.key,
            output={
                "scanned": len(files),
                "findings": summary,
                "blocking": summary["high"],  # HIGH findings a human should clear
                "details": [f.as_dict() for f in findings[:20]],
            },
            messages=[message],
        )


register_runner(SecurityAgent)
