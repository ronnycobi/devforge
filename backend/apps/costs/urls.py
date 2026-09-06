from django.urls import path

from apps.costs.api import ProjectCostEstimateView

app_name = "costs"

urlpatterns = [
    path(
        "projects/<int:project_pk>/cost-estimate/",
        ProjectCostEstimateView.as_view(),
        name="estimate",
    ),
]
