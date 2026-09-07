"""Backend Agent — implements the backend code and describes its API.

Two generation modes (task input `stack`):
- "stdlib" (default): a complete, self-contained, standard-library-only runnable
  project (flat, with test_*.py).
- "django": a Django app (models.py, tests.py, …) that DevForge wraps in a
  deterministic project scaffold (settings/manage.py/migration-free test DB), so
  the Testing Agent can run `manage.py test` against a real test database.

In both modes it persists the API design (pipeline intact), writes files into the
project git repo, commits, and compile-checks the generated Python. Honest signals
only — offline generates nothing; compile failures are reported, not hidden.
"""
from __future__ import annotations

from django.utils.text import slugify

from apps.agents.base import AgentContext, AgentResult, BaseAgent
from apps.agents.capabilities import Capability
from apps.agents.definitions import BACKEND
from apps.agents.runners import register_runner
from apps.ai_providers.base import Message
from apps.backend.parsing import parse_backend
from apps.backend.prompts import DJANGO_SYSTEM_PROMPT, SYSTEM_PROMPT, build_user_prompt
from apps.codegen.django_scaffold import scaffold_django_project
from apps.codegen.parsing import parse_files
from apps.codegen.service import materialize, verify_python
from apps.core.jsonx import extract_json
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
        stack = (context.input.get("stack") or "stdlib").strip().lower()

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

        system = DJANGO_SYSTEM_PROMPT if stack == "django" else SYSTEM_PROMPT
        response = self.router.complete(
            RoutingRequest(complexity=TaskComplexity.HIGH, task_type="backend"),
            messages=[
                Message(
                    "user",
                    build_user_prompt(architecture, requirements, schema, existing_api, brief),
                )
            ],
            system=system,
            max_tokens=4000,
        )

        source = f"agent:{self.key}#task:{context.metadata.get('task_id', '')}"
        endpoints = parse_backend(response.text)["endpoints"]
        self._persist_endpoints(ctx, endpoints, source)

        files, app_label = self._build_files(response.text, stack)
        commit_sha, verified, verify_log = None, None, ""
        if files:
            _, commit_sha = materialize(
                project,
                files,
                message=f"{stack} backend by {self.key} (task {context.metadata.get('task_id', '')})",
            )
            verified, verify_log = verify_python(files)

        messages = [
            f"[{stack}] generated {len(files)} file(s) via {response.model}."
        ]
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
                "stack": stack,
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

    def _build_files(self, text, stack):
        """Return (files_list, app_label). app_label is None outside django mode."""
        if stack != "django":
            return parse_files(text), None
        payload = extract_json(text) or {}
        app_label = payload.get("app_label") if isinstance(payload, dict) else None
        app_files = {f["path"]: f["content"] for f in parse_files(text)}
        if not app_files:
            return [], app_label
        scaffold = scaffold_django_project(app_label or "app", app_files)
        return [{"path": p, "content": c} for p, c in scaffold.items()], app_label


register_runner(BackendAgent)
