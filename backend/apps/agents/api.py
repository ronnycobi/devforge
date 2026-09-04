from django.http import Http404
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.agents.definitions import registry
from apps.agents.serializers import AgentDefinitionSerializer


class AgentListView(APIView):
    """List the platform agent catalog and each agent's capabilities."""

    def get(self, request):
        data = AgentDefinitionSerializer(registry.all(), many=True).data
        return Response(data)


class AgentDetailView(APIView):
    """Retrieve one agent definition by key."""

    def get(self, request, key):
        if key not in registry:
            raise Http404("Unknown agent")
        return Response(AgentDefinitionSerializer(registry.get(key)).data)
