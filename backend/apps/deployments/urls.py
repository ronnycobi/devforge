from django.urls import path

from apps.deployments.api import (
    DeploymentApproveView,
    DeploymentListCreateView,
    DeploymentRunView,
)

app_name = "deployments"

urlpatterns = [
    path(
        "projects/<int:project_pk>/deployments/",
        DeploymentListCreateView.as_view(),
        name="list",
    ),
    path(
        "deployments/<int:pk>/approve/",
        DeploymentApproveView.as_view(),
        name="approve",
    ),
    path("deployments/<int:pk>/run/", DeploymentRunView.as_view(), name="run"),
]
