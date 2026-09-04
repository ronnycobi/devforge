from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ai_providers.registry import registry
from apps.ai_providers.serializers import ProviderSerializer


class ProviderListView(APIView):
    """List AI providers, which are configured, and their models.

    Reports availability (SDK + key present) but never the key itself.
    """

    def get(self, request):
        data = ProviderSerializer(registry.all(), many=True).data
        return Response(data)
