from rest_framework import generics

from apps.organizations.access import organizations_for
from apps.projects.models import Project
from apps.projects.serializers import ProjectSerializer


class ProjectListCreateView(generics.ListCreateAPIView):
    """List projects across the user's organizations; create in a managed org."""

    serializer_class = ProjectSerializer

    def get_queryset(self):
        return (
            Project.objects.filter(
                organization__in=organizations_for(self.request.user)
            )
            .select_related("organization")
            .distinct()
        )

    def perform_create(self, serializer):
        project = serializer.save(created_by=self.request.user)
        # Every project starts with a default working environment.
        project.ensure_default_workspace()


class ProjectDetailView(generics.RetrieveUpdateAPIView):
    """Retrieve or update a project the user can access (membership required)."""

    serializer_class = ProjectSerializer

    def get_queryset(self):
        return Project.objects.filter(
            organization__in=organizations_for(self.request.user)
        ).select_related("organization")
