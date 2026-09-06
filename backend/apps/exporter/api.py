from django.http import HttpResponse
from rest_framework.views import APIView

from apps.exporter.service import build_export
from apps.projects.access import project_for_read


class ProjectExportView(APIView):
    """Download the project's export archive (any org member)."""

    def get(self, request, project_pk):
        project = project_for_read(request.user, project_pk)
        filename, data = build_export(project)
        response = HttpResponse(data, content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
