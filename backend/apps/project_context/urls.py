from django.urls import path

from apps.project_context.api import (
    ContextDetailView,
    ContextDigestView,
    ContextListCreateView,
)

app_name = "project_context"

urlpatterns = [
    path(
        "projects/<int:project_pk>/context/",
        ContextListCreateView.as_view(),
        name="list",
    ),
    path(
        "projects/<int:project_pk>/context/digest/",
        ContextDigestView.as_view(),
        name="digest",
    ),
    path("context/<int:pk>/", ContextDetailView.as_view(), name="detail"),
]
