from rest_framework.response import Response
from rest_framework.views import APIView

from apps.model_router.catalog import MODEL_CATALOG
from apps.model_router.router import (
    ModelRouter,
    NoModelAvailable,
    RoutingRequest,
    TaskComplexity,
)
from apps.model_router.serializers import (
    ModelProfileSerializer,
    RoutingDecisionSerializer,
    RoutingRequestSerializer,
)


class ModelListView(APIView):
    """List routable models with pricing, context window, and availability."""

    def get(self, request):
        return Response(ModelProfileSerializer(MODEL_CATALOG, many=True).data)


class RouteView(APIView):
    """Dry-run: return which model the router would pick for a task shape.

    No completion is run, so this is free — useful for cost preview and for
    showing why a model was chosen.
    """

    def post(self, request):
        serializer = RoutingRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        routing_request = RoutingRequest(
            complexity=TaskComplexity(data["complexity"]),
            required_context_tokens=data["required_context_tokens"],
            max_cost_per_mtok=data.get("max_cost_per_mtok"),
            prefer_quality=data["prefer_quality"],
            preferred_provider=data.get("preferred_provider") or None,
            preferred_model=data.get("preferred_model") or None,
            allowed_providers=data.get("allowed_providers") or None,
            task_type=data.get("task_type", ""),
        )
        try:
            decision = ModelRouter().route(routing_request)
        except NoModelAvailable as exc:
            return Response({"detail": str(exc)}, status=409)
        return Response(RoutingDecisionSerializer(decision).data)
