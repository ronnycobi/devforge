"""Run ONE real end-to-end build for a brief through the full agent pipeline.

This is the proof harness: it creates a fresh project, runs requirements →
architect → database → backend → frontend → testing → code_review → security via
the orchestrator (each depending on the last), and reports the real outcome —
which model ran, tokens/cost, files generated, whether they compiled and the
tests passed. It uses whatever provider is configured: the offline stub prints an
honest STUB warning (no real code); set ANTHROPIC_API_KEY + AI_DEFAULT_PROVIDER=
anthropic for a genuine live build.

    ../env/bin/python manage.py prove_build --brief "A URL shortener API" --stack fastapi
"""
from __future__ import annotations

import shutil

from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.ai_providers.registry import default_provider_name, get_provider
from apps.orchestrator.service import Orchestrator
from apps.organizations.models import Organization, Role
from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.projects.models import Project
from apps.repositories.service import repo_for_project

PIPELINE = ["requirements", "architect", "database", "backend", "frontend",
            "testing", "code_review", "security"]


class Command(BaseCommand):
    help = "Run one end-to-end build for a brief through the full agent pipeline."

    def add_arguments(self, parser):
        parser.add_argument("--brief", required=True, help="Product brief to build.")
        parser.add_argument("--stack", default="", help="Backend stack id (e.g. django, fastapi, node, go).")
        parser.add_argument("--org", default="Proof Org")
        parser.add_argument("--agents", default=",".join(PIPELINE),
                            help="Comma-separated agent keys to run, in order.")
        parser.add_argument("--keep", action="store_true",
                            help="Keep the project + repo instead of cleaning up.")

    def handle(self, *args, brief, stack, org, agents, keep, **opts):
        provider = default_provider_name()
        available = get_provider(provider).is_available()
        w = self.stdout.write
        w(self.style.MIGRATE_HEADING(f"\nDevForge end-to-end build: {brief!r}"))
        w(f"Provider: {provider} (available={available})")
        if provider == "stub" or not available:
            w(self.style.WARNING(
                "STUB run — no live model, so no real code is produced. Set "
                "ANTHROPIC_API_KEY and AI_DEFAULT_PROVIDER=anthropic for a live build."
            ))

        user, _ = User.objects.get_or_create(
            email="proof@devforge.local", defaults={"full_name": "Proof Runner"}
        )
        organization = Organization.objects.create(name=org, created_by=user)
        organization.add_member(user, role=Role.OWNER)
        technology = {"backend": stack} if stack else {}
        project = Project.objects.create(
            organization=organization, name="Proof Build",
            created_by=user, technology=technology,
        )
        project.ensure_default_workspace()

        orch = Orchestrator()
        keys = [a.strip() for a in agents.split(",") if a.strip()]
        task_input = {"brief": brief}
        if stack:
            task_input["stack"] = stack
        tasks, previous = [], None
        for key in keys:
            t = orch.create_task(project=project, agent_key=key,
                                 input=dict(task_input), created_by=user)
            if previous is not None:
                t.depends_on.set([previous])
            previous = t
            tasks.append(t)

        orch.run_ready(project)

        w(self.style.MIGRATE_HEADING("\nPipeline"))
        total_tokens = 0
        for t in tasks:
            t.refresh_from_db()
            total_tokens += t.tokens or 0
            out = t.output or {}
            bits = []
            for field in ("files_generated", "verified", "tests_passed", "repair_rounds",
                          "screens_written", "models_written", "findings"):
                if field in out and out[field] not in (None, 0, {}):
                    bits.append(f"{field}={out[field]}")
            mark = {"completed": "✓", "failed": "✗"}.get(t.status, "•")
            line = f"  {mark} {t.agent_key:12} {t.status:10} {t.model or '-':16} {' '.join(bits)}"
            style = self.style.SUCCESS if t.status == "completed" else self.style.ERROR
            w(style(line))
            if t.error:
                w(f"      error: {t.error[:120]}")

        repo = repo_for_project(project)
        files = repo.list_files() if repo.is_initialized else []
        w(self.style.MIGRATE_HEADING("\nGenerated repository"))
        w(f"  {len(files)} file(s): " + (", ".join(files[:20]) or "(none)"))

        ctx = ProjectContext(project)
        w(self.style.MIGRATE_HEADING("\nDigital twin populated"))
        for kind in (ContextKind.REQUIREMENT, ContextKind.ARCHITECTURE, ContextKind.API,
                     ContextKind.SCHEMA, ContextKind.SCREEN, ContextKind.SECURITY):
            c = ctx.by_kind(kind).count()
            if c:
                w(f"  {kind}: {c}")

        w(self.style.MIGRATE_HEADING("\nSummary"))
        w(f"  tokens: {total_tokens}")
        w(f"  repo path: {repo.path}")
        if provider == "stub" or not available:
            w(self.style.WARNING("  (stub run — plumbing proven; run live for real code)"))

        if not keep:
            path = repo.path
            organization.delete()  # cascades project
            shutil.rmtree(path, ignore_errors=True)
            w("  cleaned up (pass --keep to retain).")
