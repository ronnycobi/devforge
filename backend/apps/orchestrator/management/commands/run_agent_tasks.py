"""Drain runnable agent tasks for a project.

A minimal synchronous runner — the seam a background worker (Celery) will replace
later. First recovers any tasks left in-flight by a previous interruption, then
runs everything currently runnable.

    python manage.py run_agent_tasks --project <id>
"""
from django.core.management.base import BaseCommand, CommandError

from apps.orchestrator.service import Orchestrator
from apps.projects.models import Project


class Command(BaseCommand):
    help = "Recover interrupted tasks and run all runnable tasks for a project."

    def add_arguments(self, parser):
        parser.add_argument("--project", type=int, required=True, help="Project id")

    def handle(self, *args, **options):
        try:
            project = Project.objects.get(pk=options["project"])
        except Project.DoesNotExist:
            raise CommandError(f"Project {options['project']} not found")

        orchestrator = Orchestrator()

        recovered = orchestrator.recover_interrupted(project=project)
        if recovered:
            self.stdout.write(
                f"Recovered {len(recovered)} interrupted task(s)."
            )

        processed = orchestrator.run_ready(project)
        for task in processed:
            self.stdout.write(f"  task #{task.pk} [{task.agent_key}] -> {task.status}")
        self.stdout.write(
            self.style.SUCCESS(f"Processed {len(processed)} task(s).")
        )
