from rest_framework.response import Response
from rest_framework.views import APIView

from apps.technology.registry import registry
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
