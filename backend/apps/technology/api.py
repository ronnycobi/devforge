from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.project_context.models import ContextKind
from apps.project_context.services import ProjectContext
from apps.projects.access import project_for_read, require_manageable_project
from apps.technology.registry import ROLES, registry
from apps.technology.stacks import all_stacks


class TechnologyListView(APIView):
    """The technology catalog. Optional ?category= and ?language= filters."""

    def get(self, request):
        techs = registry.all()
        category = request.query_params.get("category")
        language = request.query_params.get("language")
        if category:
            techs = [t for t in techs if t.category == category]
        if language:
            techs = [t for t in techs if t.language == language or t.id == language]
        return Response(
            [
                {
                    "id": t.id,
                    "name": t.name,
                    "category": t.category,
                    "language": t.language,
                    "kind": t.kind or None,
                    "codegen": t.codegen,
                }
                for t in techs
            ]
        )


class StackListView(APIView):
    """Stacks DevForge can generate AND run today (the executable subset)."""

    def get(self, request):
        return Response(
            [
                {
                    "id": s.id,
                    "language": s.language,
                    "framework": s.framework,
                    "kind": s.kind,
                    "runnable": s.is_runnable(),
                }
                for s in all_stacks()
            ]
        )


class StackProposalView(APIView):
    """The Architect's stack proposal for a project (recommended + options)."""

    def get(self, request, project_pk):
        project = project_for_read(request.user, project_pk)
        entry = ProjectContext(project).get(ContextKind.STACK, "proposal")
        if entry is None:
            return Response(
                {"detail": "No stack proposal yet; run the Architect Agent."},
                status=404,
            )
        return Response({"project": project.id, "proposal": entry.data})


class SelectStackView(APIView):
    """User selects the project's stack. Sets Project.technology (manager-only)."""

    def post(self, request, project_pk):
        project = require_manageable_project(request.user, project_pk)
        data = request.data or {}
        selection = {}
        for role in ROLES:
            value = data.get(role)
            if not value:
                continue
            if value not in registry:
                raise ValidationError({role: f"Unknown technology '{value}'."})
            selection[role] = value
        if not selection:
            raise ValidationError("Provide at least one role (e.g. backend).")
        project.technology = {**(project.technology or {}), **selection}
        project.save(update_fields=["technology", "updated_at"])
        return Response({"project": project.id, "technology": project.technology})
