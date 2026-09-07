"""DevOps Agent — generates deployment infrastructure for the chosen stack.

Stack-aware: reads the project's technology profile and produces real infra files
(Dockerfile, docker-compose.yml, CI config) tailored to it, committed to the repo.
Honest boundary: it writes valid config but does not run containers here (no Docker
in the sandbox), and never performs a production deploy — that stays approval-gated
in the deployments module.
"""
from __future__ import annotations

from apps.agents.base import AgentContext, AgentResult, BaseAgent
from apps.agents.capabilities import Capability
from apps.agents.definitions import DEVOPS
from apps.agents.runners import register_runner
from apps.ai_providers.base import Message
from apps.codegen.parsing import parse_files
from apps.codegen.service import materialize, verify_python
from apps.model_router.router import ModelRouter, RoutingRequest, TaskComplexity
from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.projects.models import Project
from apps.technology.registry import ROLES, technology_for_role

SYSTEM_PROMPT = (
    "You are the DevOps Agent for DevForge. Given a project's technology stack and "
    "architecture, generate the deployment infrastructure as files.\n\n"
    "Respond with ONLY a JSON object with one key:\n"
    '  "files": array of {"path","content"} — real config files such as a '
    '"Dockerfile", "docker-compose.yml", and a CI workflow, tailored to the '
    "stack. Use relative paths.\n"
    "Target dev and staging; do not include production secrets. No prose outside "
    "the JSON object."
)


def _stack_summary(project) -> str:
    parts = []
    for role in ROLES:
        tech = technology_for_role(project, role)
        if tech:
            parts.append(f"{role}: {tech.name}")
    return ", ".join(parts) or "unspecified stack"


class DevOpsAgent(BaseAgent):
    key = DEVOPS.key
    name = DEVOPS.name
    description = DEVOPS.description
    capabilities = DEVOPS.capabilities

    def __init__(self, router: ModelRouter | None = None):
        self.router = router or ModelRouter()

    def execute(self, context: AgentContext) -> AgentResult:
        self.require(Capability.READ_INFRASTRUCTURE)

        if not context.project_id:
            return AgentResult.failed(self.key, "DevOps work needs a project.")

        project = Project.objects.get(id=context.project_id)
        ctx = ProjectContext(project)
        brief = (context.input.get("brief") or "").strip()

        if not ctx.by_kind(ContextKind.ARCHITECTURE).exists() and not brief:
            return AgentResult.failed(
                self.key,
                "No architecture found; run the Architect Agent first "
                "(or pass a 'brief').",
            )

        stack = _stack_summary(project)
        architecture = ctx.digest(
            kinds=[ContextKind.ARCHITECTURE, ContextKind.TECH_DECISION], max_chars=2000
        )
        user = (
            f"Technology stack: {stack}.\n\n"
            + (f"Architecture:\n{architecture}\n\n" if architecture else "")
            + "Return the JSON with the deployment infrastructure files."
        )

        response = self.router.complete(
            RoutingRequest(complexity=TaskComplexity.MEDIUM, task_type="devops"),
            messages=[Message("user", user)],
            system=SYSTEM_PROMPT,
            max_tokens=3000,
        )

        files = parse_files(response.text)
        source = f"agent:{self.key}#task:{context.metadata.get('task_id', '')}"
        commit_sha = None
        verified, verify_log = None, ""
        if files:
            _, commit_sha = materialize(
                project,
                files,
                message=f"Infra by {self.key} (task {context.metadata.get('task_id', '')})",
            )
            verified, verify_log = verify_python(files)  # usually no .py -> ok
            ctx.set(
                ContextKind.DEPLOYMENT,
                "infrastructure",
                title="Deployment infrastructure",
                content=f"Generated for {stack}.",
                data={"files": [f["path"] for f in files]},
                source=source,
            )

        n = len(files)
        message = (
            f"Generated {n} infra file(s) for {stack} via {response.model} "
            "(not executed here)."
            if n
            else f"{response.model} returned no parseable infra; nothing written."
        )
        return AgentResult.completed(
            self.key,
            output={
                "model": response.model,
                "files_generated": n,
                "stack": stack,
                "commit": commit_sha,
                "verified": verified,
            },
            messages=[message],
            model=response.model,
            usage_tokens=response.usage.total_tokens,
        )


register_runner(DevOpsAgent)
