from django.urls import path

from apps.orchestrator.api import (
    TaskApproveView,
    TaskCancelView,
    TaskDetailView,
    TaskListCreateView,
)

app_name = "orchestrator"

urlpatterns = [
    path(
        "projects/<int:project_pk>/tasks/",
        TaskListCreateView.as_view(),
        name="task-list",
    ),
    path("tasks/<int:pk>/", TaskDetailView.as_view(), name="task-detail"),
    path("tasks/<int:pk>/approve/", TaskApproveView.as_view(), name="task-approve"),
    path("tasks/<int:pk>/cancel/", TaskCancelView.as_view(), name="task-cancel"),
]
