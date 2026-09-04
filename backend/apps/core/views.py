import django
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    """Liveness probe. Public by design so load balancers can reach it.

    Returns the running Django version so a deploy can be verified end to end.
    This is the one endpoint that proves the repository foundation runs.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        return Response(
            {
                "service": "devforge",
                "status": "ok",
                "django": django.get_version(),
            }
        )
