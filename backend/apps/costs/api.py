from rest_framework.response import Response
from rest_framework.views import APIView

from apps.costs.estimator import estimate_project
from apps.costs.profiles import DEFAULT_PIPELINE
from apps.projects.access import project_for_read


class ProjectCostEstimateView(APIView):
    """Estimate the cost of building a project (ranges). No side effects.

    Body (all optional): {"agents": [...], "iterations": N, "spread": 0.4}.
    Defaults to the full specialist pipeline, one iteration.
    """

    def post(self, request, project_pk):
        project_for_read(request.user, project_pk)  # tenant gate
        data = request.data or {}
        agents = data.get("agents") or list(DEFAULT_PIPELINE)
        try:
            iterations = int(data.get("iterations", 1))
            spread = float(data.get("spread", 0.4))
        except (TypeError, ValueError):
            iterations, spread = 1, 0.4
        estimate = estimate_project(agents, iterations=iterations, spread=spread)
        return Response(estimate)
