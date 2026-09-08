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
from apps.codegen.repair import verify_and_repair
from apps.database.capabilities import get_database
from apps.database.parsing import parse_schema
from apps.database.prompts import SYSTEM_PROMPT, build_user_prompt
from apps.database.selection import recommend_database
from apps.model_router.router import ModelRouter, RoutingRequest, TaskComplexity
from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.projects.models import Project
from apps.technology.registry import technology_for_role


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

        system = SYSTEM_PROMPT
        user_prompt = build_user_prompt(architecture, requirements, api, existing, brief)
        tid = context.metadata.get("task_id", "")
        response = self._complete(system, [Message("user", user_prompt)])

        # Model source is generated only for a backend DevForge can build and
        # verify today (Django). For other backends the schema design is recorded
        # but code generation is honestly deferred, not faked.
        backend_tech = technology_for_role(project, "backend")
        db_tech = technology_for_role(project, "database")
        can_generate = backend_tech is None or backend_tech.id == "django"

        # Database is technology-agnostic: reason from the chosen engine's real
        # capabilities, and if none is chosen, recommend one from the requirements
        # (never auto-PostgreSQL) and record the decision in the twin.
        db_profile = get_database(db_tech.id) if db_tech else None
        recommendation = None
        if db_tech is None:
            recommendation = recommend_database(f"{requirements} {architecture} {brief}")
            db_profile = get_database(recommendation["database"])
            rec_name = db_profile.name if db_profile else recommendation["database"]
            ctx.set(
                ContextKind.TECH_DECISION, "database-recommendation",
                title=f"Recommended database: {rec_name}",
                content=recommendation["reason"],
                data={
                    "database": recommendation["database"],
                    "category": db_profile.category.value if db_profile else None,
                    "reason": recommendation["reason"],
                    "requirement_matched": recommendation["matched"],
                },
                source=f"agent:{self.key}#task:{tid}",
            )

        # Generate + compile-repair the model source through the shared loop.
        # Tests aren't run: a lone models module has no runnable project around it
        # (the backend agent scaffolds that), so compile is the honest check here.
        files, commit_sha, verified, verify_log, rounds, model, tokens = (
            [], None, None, "", 0, response.model, response.usage.total_tokens
        )
        final_text = response.text
        if can_generate:
            outcome = verify_and_repair(
                complete=lambda messages: self._complete(system, messages),
                project=project,
                initial_response=response,
                user_prompt=user_prompt,
                build_files=lambda text: parse_files(text),
                materialize_message=f"Data models by {self.key} (task {tid})",
                max_repairs=int(context.input.get("max_repairs", 2)),
                run_tests=False,
            )
            files, commit_sha = outcome.files, outcome.commit_sha
            verified, verify_log, rounds = outcome.compiled, outcome.compile_log, outcome.repair_rounds
            model, tokens, final_text = outcome.model, outcome.total_tokens, outcome.final_text

        # Persist the schema design from the final (possibly repaired) response.
        models = parse_schema(final_text)["models"]
        source = f"agent:{self.key}#task:{tid}"
        for m in models:
            ctx.set(
                ContextKind.SCHEMA,
                slugify(m["name"])[:255] or "model",
                title=m["name"],
                content=m["description"],
                data={"fields": m["fields"], "relations": m["relations"]},
                source=source,
            )

        n = len(models)
        db_label = db_tech.name if db_tech else "the chosen database"
        messages = [
            f"Designed {n} data model(s) for {db_label} and generated "
            f"{len(files)} file(s) via {model}."
        ]
        if files:
            check = "passed" if verified else "FAILED"
            note = f"Compile check: {check} — {verify_log}"
            if rounds:
                note += f" (self-repair rounds: {rounds})"
            messages.append(note)
        elif not can_generate:
            messages.append(
                f"Code generation for a {backend_tech.name} backend is planned; "
                "recorded the schema design only."
            )
        elif not n:
            messages = [f"{model} returned no parseable schema; nothing written."]

        if recommendation:
            rec_name = db_profile.name if db_profile else recommendation["database"]
            messages.append(f"No database chosen — recommended {rec_name}: {recommendation['reason']}.")
        if db_profile and not db_profile.supports("migrations"):
            messages.append(
                f"{db_profile.name} is a {db_profile.category.value} store; "
                "relational migrations do not apply — it is modelled on its own terms."
            )

        return AgentResult.completed(
            self.key,
            output={
                "model": model,
                "models_written": n,
                "files_generated": len(files),
                "backend_stack": backend_tech.id if backend_tech else None,
                "database_stack": db_tech.id if db_tech else None,
                "database": db_tech.id if db_tech else (recommendation["database"] if recommendation else None),
                "database_category": db_profile.category.value if db_profile else None,
                "database_capabilities": db_profile.as_dict() if db_profile else None,
                "database_recommended": recommendation is not None,
                "code_generated": bool(files),
                "commit": commit_sha,
                "verified": verified,
                "repair_rounds": rounds,
                "compile_log": verify_log,
            },
            messages=messages,
            model=model,
            usage_tokens=tokens,
        )

    def _complete(self, system, messages):
        return self.router.complete(
            RoutingRequest(complexity=TaskComplexity.HIGH, task_type="schema"),
            messages=messages,
            system=system,
            max_tokens=3000,
        )


register_runner(DatabaseAgent)
