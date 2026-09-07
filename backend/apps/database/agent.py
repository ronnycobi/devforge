"""Database Agent — designs the relational data model.

Persists each entity as a SCHEMA context entry (keyed by name, upsert). Declares/
enforces read-architecture + read-database + write-migrations + run-tests; it has
no capability to touch production data. Producing actual migrations belongs to the
build/export phases; this designs the schema they will emit.
"""
from __future__ import annotations

from django.utils.text import slugify

from apps.agents.base import AgentContext, AgentResult, BaseAgent
from apps.agents.capabilities import Capability
from apps.agents.definitions import DATABASE
from apps.agents.runners import register_runner
from apps.ai_providers.base import Message
from apps.codegen.parsing import parse_files
from apps.codegen.service import materialize, verify_python
from apps.database.parsing import parse_schema
from apps.database.prompts import SYSTEM_PROMPT, build_user_prompt
from apps.model_router.router import ModelRouter, RoutingRequest, TaskComplexity
from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.projects.models import Project


class DatabaseAgent(BaseAgent):
    key = DATABASE.key
    name = DATABASE.name
    description = DATABASE.description
    capabilities = DATABASE.capabilities

    def __init__(self, router: ModelRouter | None = None):
        self.router = router or ModelRouter()

    def execute(self, context: AgentContext) -> AgentResult:
        self.require(Capability.WRITE_MIGRATIONS)

        if not context.project_id:
            return AgentResult.failed(self.key, "Schema work needs a project.")

        project = Project.objects.get(id=context.project_id)
        ctx = ProjectContext(project)
        brief = (context.input.get("brief") or "").strip()

        has_upstream = (
            ctx.by_kind(ContextKind.ARCHITECTURE).exists()
            or ctx.by_kind(ContextKind.REQUIREMENT).exists()
        )
        if not has_upstream and not brief:
            return AgentResult.failed(
                self.key,
                "No requirements or architecture found; run those agents first "
                "(or pass a 'brief').",
            )

        architecture = ctx.digest(kinds=[ContextKind.ARCHITECTURE], max_chars=2000)
        requirements = ctx.digest(kinds=[ContextKind.REQUIREMENT], max_chars=2000)
        api = ctx.digest(kinds=[ContextKind.API], max_chars=1500)
        existing = ctx.digest(kinds=[ContextKind.SCHEMA], max_chars=1500)

        response = self.router.complete(
            RoutingRequest(complexity=TaskComplexity.HIGH, task_type="schema"),
            messages=[
                Message("user", build_user_prompt(architecture, requirements, api, existing, brief))
            ],
            system=SYSTEM_PROMPT,
            max_tokens=3000,
        )

        models = parse_schema(response.text)["models"]
        source = f"agent:{self.key}#task:{context.metadata.get('task_id', '')}"
        for model in models:
            ctx.set(
                ContextKind.SCHEMA,
                slugify(model["name"])[:255] or "model",
                title=model["name"],
                content=model["description"],
                data={"fields": model["fields"], "relations": model["relations"]},
                source=source,
            )

        # Generate model source -> repo, then compile-check it.
        files = parse_files(response.text)
        commit_sha = None
        verified, verify_log = None, ""
        if files:
            _, commit_sha = materialize(
                project,
                files,
                message=f"Data models by {self.key} (task {context.metadata.get('task_id', '')})",
            )
            verified, verify_log = verify_python(files)

        n = len(models)
        messages = [
            f"Designed {n} data model(s) and generated {len(files)} file(s) "
            f"via {response.model}."
        ]
        if files:
            messages.append(
                f"Compile check: {'passed' if verified else 'FAILED'} — {verify_log}"
            )
        elif not n:
            messages = [f"{response.model} returned no parseable schema; nothing written."]

        return AgentResult.completed(
            self.key,
            output={
                "model": response.model,
                "models_written": n,
                "files_generated": len(files),
                "commit": commit_sha,
                "verified": verified,
                "compile_log": verify_log,
            },
            messages=messages,
            model=response.model,
            usage_tokens=response.usage.total_tokens,
        )


register_runner(DatabaseAgent)
