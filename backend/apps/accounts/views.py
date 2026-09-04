from rest_framework.generics import RetrieveAPIView

from apps.accounts.serializers import UserSerializer


class MeView(RetrieveAPIView):
    """Return the authenticated user and the organizations they belong to."""

    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user
