from django.shortcuts import get_object_or_404
from rest_framework import generics

from apps.organizations.access import organizations_for
from apps.projects.models import Project
from apps.workspaces.models import Workspace
from apps.workspaces.serializers import WorkspaceSerializer


class WorkspaceListCreateView(generics.ListCreateAPIView):
    """Workspaces of a single project the caller can access."""

    serializer_class = WorkspaceSerializer

    def get_project(self):
        # 404 (not 403) for projects outside the user's organizations, so we
        # never confirm the existence of another tenant's project.
        return get_object_or_404(
            Project.objects.filter(
                organization__in=organizations_for(self.request.user)
            ),
            pk=self.kwargs["project_pk"],
        )

    def get_queryset(self):
        return self.get_project().workspaces.all()

    def perform_create(self, serializer):
        serializer.save(project=self.get_project())
