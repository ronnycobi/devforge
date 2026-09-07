"""Backend Agent — implements the backend code and describes its API.

Reads the design (architecture, requirements, schema), asks a model to generate
Django source files AND the API they expose, then:
  1. persists the endpoints as API context entries (so the pipeline stays intact),
  2. writes the files into the project's git repo and commits them,
  3. compile-checks the generated Python in the build sandbox.
The result reports files generated, the commit, and whether they compiled — an
honest signal, never faked. Offline (stub) it generates nothing and says so.
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
from apps.codegen.parsing import parse_files
from apps.codegen.service import materialize, verify_python
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
            system=SYSTEM_PROMPT,
            max_tokens=4000,
        )

        source = f"agent:{self.key}#task:{context.metadata.get('task_id', '')}"

        # 1. Persist the API design (keeps the pipeline's context intact).
        endpoints = parse_backend(response.text)["endpoints"]
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

        # 2 & 3. Generate code -> repo, then compile-check it.
        files = parse_files(response.text)
        commit_sha = None
        verified, verify_log = None, ""
        if files:
            _, commit_sha = materialize(
                project,
                files,
                message=f"Backend code by {self.key} (task {context.metadata.get('task_id', '')})",
            )
            verified, verify_log = verify_python(files)

        messages = [
            f"Designed {len(endpoints)} endpoint(s) and generated {len(files)} "
            f"file(s) via {response.model}."
        ]
        if files:
            messages.append(
                f"Compile check: {'passed' if verified else 'FAILED'} — {verify_log}"
            )
        elif not endpoints:
            messages = [f"{response.model} returned no parseable output; nothing written."]

        return AgentResult.completed(
            self.key,
            output={
                "model": response.model,
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


register_runner(BackendAgent)
