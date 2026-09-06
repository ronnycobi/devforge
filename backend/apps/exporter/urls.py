from django.urls import path

from apps.exporter.api import ProjectExportView

app_name = "exporter"

urlpatterns = [
    path(
        "projects/<int:project_pk>/export/",
        ProjectExportView.as_view(),
        name="export",
    ),
]
