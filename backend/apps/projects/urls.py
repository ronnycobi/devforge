from django.urls import path

from apps.projects.api import ProjectDetailView, ProjectListCreateView
from apps.workspaces.api import WorkspaceListCreateView

app_name = "projects"

urlpatterns = [
    path("projects/", ProjectListCreateView.as_view(), name="list"),
    path("projects/<int:pk>/", ProjectDetailView.as_view(), name="detail"),
    path(
        "projects/<int:project_pk>/workspaces/",
        WorkspaceListCreateView.as_view(),
        name="workspace-list",
    ),
]
